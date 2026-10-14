"""Observable trajectories and input provenance for a completed render."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import __version__ as pillow_version

from .config import MODEL_VERSION, REPO_ROOT, RenderConfig
from .input_loader import InputBundle
from .object_dynamics import ObjectAgent
from .transition_controller import mode_for_stage


def readable_path(path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(REPO_ROOT).as_posix() if resolved.is_relative_to(REPO_ROOT) else resolved.as_posix()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class RunReport:
    def __init__(self, config: RenderConfig, bundle: InputBundle) -> None:
        self.config = config
        self.state_digest = hashlib.sha256()
        self.frame_digest = hashlib.sha256()
        self.frame_count = 0
        self.scenes = [
            {
                "scene_id": scene.scene_id, "stage": scene.stage,
                "title": scene.title, "story": scene.story,
                "emotion_label": scene.emotion_label,
                "emotion_intensity": scene.emotion_intensity,
                "start_frame": index * config.scene_frames,
                "start_seconds": index * config.scene_seconds,
                "duration": config.scene_seconds,
                "background": readable_path(scene.background_path),
                "objects": [{"id": obj.object_id, "name": obj.name, "file": readable_path(obj.path)} for obj in scene.objects],
                "transition_mode": mode_for_stage(scene.stage).value,
                "transition_start_frame": (index + 1) * config.scene_frames - min(config.scene_frames, max(1, round(config.transition_seconds * config.fps))),
                "frame_count": 0, "activity_sum": 0.0,
                "exploration_sum": 0.0, "audio_rms_sum": 0.0,
                "trajectory_samples": [],
            }
            for index, scene in enumerate(bundle.scenes)
        ]
        self.carryovers: list[dict[str, float | int]] = []
        self.inputs = [{"path": readable_path(path), "sha256": file_digest(path)} for path in bundle.input_files]
        self.warnings = list(bundle.warnings)
        self.semantic: dict = {}

    def record(
        self, scene_index: int, local_frame: int, agents: Sequence[ObjectAgent],
        trace: np.ndarray, activity: float, exploration: float, audio_rms: float,
        pixels: np.ndarray,
    ) -> None:
        self.frame_count += 1
        scene = self.scenes[scene_index]
        scene["frame_count"] += 1
        scene["activity_sum"] += activity
        scene["exploration_sum"] += exploration
        scene["audio_rms_sum"] += audio_rms
        values = np.asarray([
            [*agent.position, *agent.velocity, agent.scale, agent.rotation, agent.opacity, agent.energy]
            for agent in agents
        ], dtype="<f8")
        self.state_digest.update(values.tobytes())
        self.state_digest.update(np.asarray(trace, dtype="<f4").tobytes())
        self.frame_digest.update(np.ascontiguousarray(pixels).tobytes())
        if local_frame % max(1, self.config.fps // 4) == 0 or local_frame == self.config.scene_frames - 1:
            scene["trajectory_samples"].append({
                "frame": scene_index * self.config.scene_frames + local_frame,
                "agents": [
                    {"id": agent.object_id, "position": agent.position.tolist(),
                     "velocity": agent.velocity.tolist(), "scale": agent.scale,
                     "rotation": agent.rotation, "opacity": agent.opacity,
                     "beat": agent.beat, "trace_force": agent.trace_force.tolist(),
                     "semantic_force": agent.semantic_force.tolist()}
                    for agent in agents
                ],
                "trace_mass": float(trace.sum()), "activity": activity,
                "exploration_strength": exploration, "audio_rms": audio_rms,
            })

    def save(self, audio_report: dict, elapsed_seconds: float, video_sha256: str) -> dict:
        if self.frame_count != self.config.total_frames:
            raise ValueError("Cannot report a partial video as completed")
        scenes = []
        for scene in self.scenes:
            item = dict(scene)
            count = item["frame_count"]
            item["mean_activity"] = item.pop("activity_sum") / count
            item["mean_exploration_strength"] = item.pop("exploration_sum") / count
            item["mean_audio_rms"] = item.pop("audio_rms_sum") / count
            scenes.append(item)
        report = {
            "model": "DreamModel", "version": MODEL_VERSION, "status": "complete",
            "mode": "smoke" if self.config.smoke else "final",
            "seed": self.config.seed, "resolution": [self.config.width, self.config.height],
            "fps": self.config.fps, "duration": self.config.duration,
            "total_frames": self.frame_count, "scene_duration": self.config.scene_seconds,
            "mean_activity": sum(scene["mean_activity"] * scene["frame_count"] for scene in scenes) / self.frame_count,
            "mean_exploration_strength": sum(scene["mean_exploration_strength"] * scene["frame_count"] for scene in scenes) / self.frame_count,
            "transition_window_seconds": self.config.transition_seconds,
            "trace_memory": {"size": [self.config.trace_width, self.config.trace_height],
                             "decay_per_frame": self.config.trace_decay,
                             "scene_retention": self.config.memory_retention},
            "scene_memory_carryovers": self.carryovers,
            "semantic_conditioning": self.semantic,
            "input_files": self.inputs, "audio": audio_report,
            "output_file": readable_path(self.config.output_path), "scenes": scenes,
            "state_sha256": self.state_digest.hexdigest(),
            "raw_frames_sha256": self.frame_digest.hexdigest(), "video_sha256": video_sha256,
            "environment": {"python": platform.python_version(), "numpy": np.__version__, "Pillow": pillow_version},
            "reproducibility_scope": "Same input bytes, seed, settings and numerical/media environment; compare state and raw-frame hashes.",
            "elapsed_render_seconds": elapsed_seconds, "warnings": self.warnings,
        }
        self.config.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return report
