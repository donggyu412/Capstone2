"""Fixed project timings and independent DreamModel rendering settings."""

from dataclasses import dataclass,field
import math
from pathlib import Path
from .audience import AudienceAtmosphere

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_VERSION = "1.2.0"


@dataclass(frozen=True)
class RenderConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    scene_seconds: float = 75.0
    transition_seconds: float = 6.0
    seed: int = 101
    smoke: bool = False
    input_root: Path = REPO_ROOT / "team4" / "input"
    output_path: Path = REPO_ROOT / "team4" / "output" / "dreammodel_final.mp4"
    report_path: Path = REPO_ROOT / "team4" / "output" / "dreammodel_run_report.json"
    trace_width: int = 128
    trace_height: int = 72
    trace_decay: float = 0.980
    memory_retention: float = 0.35
    semantic_config: Path = Path(__file__).with_name("semantic_config.json")
    conditioning_off: str | None = None
    scene_count: int = 4
    preview_start_seconds: float | None = None
    preview_seconds: float | None = None
    audience: AudienceAtmosphere = field(default_factory=AudienceAtmosphere)

    def __post_init__(self) -> None:
        if (self.preview_start_seconds is None)!=(self.preview_seconds is None):
            raise ValueError('Preview start and duration must be specified together')
        if self.preview_seconds is not None and (not math.isfinite(self.preview_seconds) or self.preview_seconds<=0
                or not math.isfinite(self.preview_start_seconds) or self.preview_start_seconds<0):
            raise ValueError('Preview window must be finite and positive')
        if self.conditioning_off not in (None, 'story', 'emotion', 'sound'):
            raise ValueError('conditioning_off must be story, emotion or sound')
        if self.width < 2 or self.height < 2 or self.width % 2 or self.height % 2:
            raise ValueError("MP4 width and height must be positive even integers")
        if self.fps != 30:
            raise ValueError("The shared project clock is fixed at 30 fps")
        if not math.isfinite(self.scene_seconds) or self.scene_seconds <= 0:
            raise ValueError("Scene duration must be finite and positive")
        frames = self.scene_seconds * self.fps
        if not math.isclose(frames, round(frames), abs_tol=1e-8):
            raise ValueError("Scene duration must contain an integer number of frames")
        if not 0 < self.transition_seconds <= self.scene_seconds:
            raise ValueError("Transition window must be positive and fit within a scene")
        if not 0 <= self.memory_retention <= 1 or not 0 <= self.trace_decay < 1:
            raise ValueError("Trace decay/carryover must be normalized")
        if self.trace_width < 2 or self.trace_height < 2:
            raise ValueError("Trace dimensions must be at least 2")
        if self.output_path.suffix.lower() != ".mp4" or self.report_path.suffix.lower() != ".json":
            raise ValueError("Output must be MP4 and report must be JSON")
        for destination in (self.output_path, self.report_path):
            if destination.resolve().is_relative_to(self.input_root.resolve()):
                raise ValueError("Generated output must not overwrite shared inputs")

    @property
    def scene_frames(self) -> int:
        return round(self.scene_seconds * self.fps)

    @property
    def total_frames(self) -> int:
        if self.preview_seconds is not None:return round(self.preview_seconds*self.fps)
        return self.scene_count * self.scene_frames

    @property
    def duration(self) -> float:
        return self.total_frames / self.fps
