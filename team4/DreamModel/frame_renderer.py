"""Unicode-safe image composition and streaming H.264 output for DreamModel.

The compositor visualizes agent state; it neither generates assets nor simulates
background cells. Its small ghost history is a visual accompaniment to the
simulation's shared, persistent trace field.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageEnhance, ImageOps


def find_ffmpeg() -> str:
    """Find a system encoder or the executable supplied by imageio-ffmpeg."""
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError(
            "FFmpeg is unavailable. Install DreamModel/requirements.txt in the "
            "Python environment used to run this command."
        ) from exc


def subprocess_options() -> dict[str, Any]:
    """Keep encoder/decoder helpers invisible when launched on Windows."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def load_background(path: Path | str, width: int, height: int) -> np.ndarray:
    """Load the supplied plate without inventing or regenerating its content."""
    with Image.open(Path(path)) as image:
        plate = ImageOps.fit(image.convert("RGB"), (width, height), Image.Resampling.LANCZOS)
        return np.asarray(plate, dtype=np.uint8).copy()


def load_sprite(path: Path | str, max_side: int = 512) -> np.ndarray:
    """Preserve an upstream transparent sprite and its Korean filename."""
    if max_side < 1:
        raise ValueError("max_side must be positive")
    with Image.open(Path(path)) as image:
        sprite = image.convert("RGBA")
        sprite.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return np.asarray(sprite, dtype=np.uint8).copy()


@dataclass(frozen=True)
class _Pose:
    x: float
    y: float
    scale: float
    rotation: float
    opacity: float

    @classmethod
    def from_agent(cls, agent: Any) -> "_Pose":
        return cls(float(agent.position[0]), float(agent.position[1]),
                   float(agent.scale), float(agent.rotation), float(agent.opacity))


class FrameRenderer:
    """Compose moving translucent object memories over the original plate.

    A fresh renderer fed the same frame sequence produces identical RGB pixels.
    Trace brightness uses a fixed bounded compression, never per-frame auto gain.
    Agent lists and sprite lists must have the same upstream object order.
    """

    def __init__(self, width: int, height: int, fps: int = 30, *,
                 trace_alpha_max: int = 20, ghost_gains: Sequence[float] = (.045, .075),
                 sprite_height: float = .44) -> None:
        if width < 2 or height < 2 or fps < 1:
            raise ValueError("Frame dimensions and fps must be positive")
        self.width, self.height, self.fps = width, height, fps
        if not 0 <= trace_alpha_max <= 32 or not .1 <= sprite_height <= .6:
            raise ValueError("Trace opacity or sprite size exceeds the identity-preserving range")
        if len(ghost_gains) != 2 or any(not 0 <= gain <= .15 for gain in ghost_gains):
            raise ValueError("Two bounded ghost opacity gains are required")
        self.trace_alpha_max, self.ghost_gains, self.sprite_height = trace_alpha_max, ghost_gains, sprite_height
        self._prepared: dict[int, tuple[np.ndarray, Image.Image]] = {}
        # Reuse transformed historical poses when drawing ghosts. Keep this
        # bounded: even a 300-second render must not accumulate every frame.
        self._transformed: OrderedDict[tuple[int, int, float], Image.Image] = OrderedDict()
        self._history: dict[int, deque[_Pose]] = {}
        self._history_sources: dict[int, Image.Image] = {}
        self._inactive_age: dict[int, int] = {}
        self._last_visibility: dict[int, float] = {}
        self._history_length = max(4, round(0.60 * fps))
        self._trace_ink = Image.new("RGB", (width, height), (104, 145, 174))

    def _sprite(self, array: np.ndarray) -> Image.Image:
        key = id(array)
        cached = self._prepared.get(key)
        if cached is not None and cached[0] is array:
            return cached[1]
        if array.ndim != 3 or array.shape[2] != 4 or array.dtype != np.uint8:
            raise ValueError("Sprites must be uint8 RGBA arrays")
        # Preserve source RGB and alpha exactly. Movement/opacity are agent
        # states; they must not replace the source with a grey approximation.
        result = Image.fromarray(array)
        self._prepared[key] = (array, result)
        return result

    def _transform(self, sprite: Image.Image, pose: _Pose, gain: float) -> Image.Image:
        side = max(4, round(min(self.height * self.sprite_height, self.width * 0.29) * max(0.05, pose.scale)))
        cache_key = (id(sprite), side, pose.rotation)
        cached = self._transformed.get(cache_key)
        if cached is None:
            ratio = side / max(sprite.size)
            size = (max(1, round(sprite.width * ratio)), max(1, round(sprite.height * ratio)))
            cached = sprite.resize(size, Image.Resampling.BILINEAR)
            cached = cached.rotate(pose.rotation, Image.Resampling.BILINEAR, expand=True)
            # Resampling is sufficient; blur must not erase page/hand details.
            self._transformed[cache_key] = cached
            if len(self._transformed) > 128:
                self._transformed.popitem(last=False)
        else:
            self._transformed.move_to_end(cache_key)
        transformed = cached.copy()
        alpha_gain = float(np.clip(pose.opacity * gain, 0, 1))
        transformed.putalpha(transformed.getchannel("A").point(
            [round(value * alpha_gain) for value in range(256)]))
        return transformed

    @staticmethod
    def _paste(canvas: Image.Image, sprite: Image.Image, center: tuple[float, float]) -> None:
        origin = (round(center[0] - sprite.width / 2), round(center[1] - sprite.height / 2))
        canvas.paste(sprite, origin, sprite.getchannel("A"))

    def _fragment(self, canvas: Image.Image, sprite: Image.Image, pose: _Pose,
                  progress: float, seed: int) -> None:
        """Disperse intact impressions; the original silhouette stays whole."""
        for index in range(3):
            variation = ((seed + 1) * 73856093 + index * 19349663) % 997 / 997
            angle = index * 2 * np.pi / 3 + variation + pose.rotation * np.pi / 180
            radius = self.height * .055 * progress * (.6 + .4 * variation)
            impression = sprite.copy()
            impression.putalpha(impression.getchannel("A").point(
                [round(a * .35 * progress) for a in range(256)]))
            self._paste(canvas, impression, (pose.x * self.width + np.cos(angle) * radius,
                                             pose.y * self.height + np.sin(angle) * radius))
        self._paste(canvas, sprite, (pose.x * self.width, pose.y * self.height))

    def _reveal_mask(self, trace: np.ndarray, agents: Sequence[Any], mode: str,
                     progress: float) -> Image.Image:
        """Trace and live positions decide where the next memory becomes visible."""
        if progress <= 0:
            return Image.new("L", (self.width, self.height), 0)
        if progress >= 1:
            return Image.new("L", (self.width, self.height), 255)
        rows, columns = np.indices(trace.shape, dtype=np.float32)
        x, y = columns / max(1, trace.shape[1] - 1), rows / max(1, trace.shape[0] - 1)
        proximity = np.zeros_like(trace)
        for agent in agents:
            distance = (x - float(agent.position[0])) ** 2 + (y - float(agent.position[1])) ** 2
            proximity = np.maximum(proximity, np.exp(-distance / 0.055))
        memory = trace / (1 + trace)
        if mode == "FRAGMENTATION":
            pattern = 0.40 * memory + 0.60 * proximity
        elif mode == "ACCUMULATION":
            pattern = 0.75 * memory + 0.25 * proximity
        elif mode == "EMERGENCE":
            pattern = 0.45 * (1 - memory) + 0.55 * proximity
        else:
            pattern = 0.7 * memory + 0.3 * proximity
        # The envelope is exactly 0 / 1 at the window boundaries while each
        # intermediate reveal is shaped by the actual memory and agent state.
        field = np.clip(progress + 1.6 * progress * (1 - progress) * (pattern - .5), 0, 1)
        return Image.fromarray(np.uint8(field * 255)).resize(
            (self.width, self.height), Image.Resampling.BILINEAR)

    def render(self, background: np.ndarray, sprites: Sequence[np.ndarray], agents: Sequence[Any],
               trace: np.ndarray, *, transition: Any = None,
               next_background: np.ndarray | None = None,
               next_sprites: Sequence[np.ndarray] = (), next_agents: Sequence[Any] = ()) -> np.ndarray:
        if background.shape != (self.height, self.width, 3) or background.dtype != np.uint8:
            raise ValueError("Background must match renderer dimensions as uint8 RGB")
        if len(sprites) != len(agents):
            raise ValueError("Every object agent must have exactly one sprite")
        if len(next_sprites) != len(next_agents):
            raise ValueError("Every upcoming object agent must have exactly one sprite")
        trace = np.asarray(trace, dtype=np.float32)
        if trace.ndim != 2 or not np.isfinite(trace).all() or np.any(trace < 0):
            raise ValueError("Trace must be a finite, nonnegative 2D field")
        canvas = Image.fromarray(background)
        progress, mode = 0.0, ""
        if transition is not None:
            progress = float(np.clip(transition.progress, 0, 1))
            mode = getattr(transition.mode, "value", transition.mode)
        if next_background is not None and transition is not None:
            if next_background.shape != background.shape or next_background.dtype != np.uint8:
                raise ValueError("Next background must have the same RGB dimensions")
            mask = self._reveal_mask(trace, agents, mode, progress)
            canvas = Image.composite(Image.fromarray(next_background), canvas, mask)

        memory = trace / (.25 + trace)
        trace_mask = Image.fromarray(np.uint8(memory * self.trace_alpha_max)).resize(
            (self.width, self.height), Image.Resampling.BILINEAR)
        canvas = Image.composite(self._trace_ink, canvas, trace_mask)
        all_pairs = [(sprite, agent, False) for sprite, agent in zip(sprites, agents)]
        if transition is not None:
            all_pairs += [(sprite, agent, True) for sprite, agent in zip(next_sprites, next_agents)]
        active_ids = {id(agent) for _, agent, _ in all_pairs}
        for key in list(self._history):
            if key in active_ids:
                self._inactive_age[key] = 0
                continue
            age = self._inactive_age.get(key, 0) + 1
            self._inactive_age[key] = age
            if age >= self._history_length:
                del self._history[key], self._history_sources[key], self._inactive_age[key], self._last_visibility[key]
                continue
            # A scene boundary does not abruptly erase the last silhouettes.
            old_pose = self._history[key][-1]
            ghost = self._transform(self._history_sources[key], old_pose,
                                    .12 * self._last_visibility[key] * (1 - age / self._history_length))
            self._paste(canvas, ghost, (old_pose.x * self.width, old_pose.y * self.height))
        for array, agent, upcoming in all_pairs:
            source, pose = self._sprite(array), _Pose.from_agent(agent)
            reveal = progress * progress * (3 - 2 * progress)
            visibility = 1.0
            if upcoming:
                visibility = reveal
                if mode == "ACCUMULATION":
                    incoming_progress = min(1.0, progress * 1.2)
                    visibility = incoming_progress ** 2 * (3 - 2 * incoming_progress)
            elif transition is not None and next_background is not None:
                # Both the outgoing body and its older ghost poses must finish
                # fading inside the window, not drop abruptly at the boundary.
                visibility = 1 - reveal
                if mode == "ACCUMULATION":
                    outgoing_progress = progress ** 2.2
                    visibility = 1 - outgoing_progress ** 2 * (3 - 2 * outgoing_progress)
            history = self._history.setdefault(id(agent), deque(maxlen=self._history_length))
            self._history_sources[id(agent)] = source
            self._inactive_age[id(agent)] = 0
            self._last_visibility[id(agent)] = visibility
            for fraction, gain in zip((.75, .35), self.ghost_gains):
                age = max(1, round(self._history_length * fraction))
                if len(history) >= age:
                    old_pose = history[-age]
                    ghost = self._transform(source, old_pose, gain * visibility)
                    self._paste(canvas, ghost, (old_pose.x * self.width, old_pose.y * self.height))
            if pose.opacity * visibility > 0.001:
                current = self._transform(source, pose, visibility)
                if mode == "FRAGMENTATION" and progress > 0 and not upcoming:
                    self._fragment(canvas, current, pose, progress, int(getattr(agent, "seed", 0)))
                else:
                    self._paste(canvas, current, (pose.x * self.width, pose.y * self.height))
            history.append(pose)

        if mode == "DISSOLUTION" and next_background is None:
            # Fade the entire last memory, including residual ghosts, to black.
            smooth = progress * progress * (3 - 2 * progress)
            canvas = ImageEnhance.Brightness(canvas).enhance(1 - smooth)
        return np.asarray(canvas, dtype=np.uint8).copy()


class VideoWriter:
    """Stream RGB frames into H.264; publish only a successfully closed MP4.

    Existing output is preserved if encoding fails. No frames are collected in
    memory. Optional audio is padded with silence or truncated to video length.
    """

    def __init__(self, path: Path | str, width: int, height: int, fps: int,
                 *, audio_path: Path | str | None = None, expected_frames: int | None = None,
                 ffmpeg_path: str | None = None, crf: int = 20,
                 keyframe_interval: int | None = None) -> None:
        if width < 2 or height < 2 or width % 2 or height % 2 or fps < 1:
            raise ValueError("H.264 yuv420p requires positive even dimensions and positive fps")
        if expected_frames is not None and expected_frames < 1:
            raise ValueError("expected_frames must be positive")
        if not 0 <= crf <= 51 or (keyframe_interval is not None and keyframe_interval < 1):
            raise ValueError('Invalid H.264 quality or keyframe interval')
        self.path = Path(path)
        self.width, self.height, self.fps = width, height, fps
        self.expected_frames, self.frame_count = expected_frames, 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        audio = Path(audio_path).resolve() if audio_path is not None else None
        if audio is not None and not audio.is_file():
            raise FileNotFoundError(f"Audio file does not exist: {audio}")
        executable = ffmpeg_path or find_ffmpeg()
        handle, temporary_path = tempfile.mkstemp(prefix=f".{self.path.stem}-", suffix=".mp4", dir=self.path.parent)
        os.close(handle)
        self._temporary = Path(temporary_path)
        self._errors = tempfile.TemporaryFile()
        self._closed = False
        command = [executable, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
                   "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                   "-r", str(fps), "-i", "pipe:0"]
        if audio is not None:
            command += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                        "-af", "apad", "-c:a", "aac", "-b:a", "128k", "-shortest"]
        else:
            command += ["-an"]
        command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart"]
        if keyframe_interval is not None:
            command += ['-g',str(keyframe_interval),'-keyint_min',str(keyframe_interval),'-sc_threshold','0']
        if expected_frames is not None:
            command += ["-t", f"{expected_frames / fps:.9f}"]
        command += [str(self._temporary)]
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=self._errors, **subprocess_options())
        except BaseException:
            self._errors.close()
            self._temporary.unlink(missing_ok=True)
            raise

    def __enter__(self) -> "VideoWriter":
        return self

    def _diagnostic(self) -> str:
        self._errors.seek(0)
        return self._errors.read().decode("utf-8", errors="replace").strip()[-4000:]

    def write(self, frame: np.ndarray) -> None:
        if self._closed:
            raise RuntimeError("Cannot write after video is closed")
        if frame.shape != (self.height, self.width, 3) or frame.dtype != np.uint8:
            raise ValueError("Video frames must match writer dimensions as uint8 RGB")
        if self.expected_frames is not None and self.frame_count >= self.expected_frames:
            raise ValueError("More frames supplied than expected_frames")
        try:
            self._process.stdin.write(np.ascontiguousarray(frame).tobytes())
        except (BrokenPipeError, OSError) as exc:
            self._process.wait()
            message = self._diagnostic()
            self.abort()
            raise RuntimeError(f"FFmpeg failed while writing video: {message}") from exc
        self.frame_count += 1

    def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait()
        try:
            self._process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        self._errors.close()
        self._temporary.unlink(missing_ok=True)

    def close(self) -> Path:
        if self._closed:
            return self.path
        if self.frame_count == 0 or (self.expected_frames is not None and self.frame_count != self.expected_frames):
            self.abort()
            raise ValueError(f"Video frame count {self.frame_count} does not match {self.expected_frames}")
        try:
            self._process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        code = self._process.wait()
        message = self._diagnostic()
        self._errors.close()
        self._closed = True
        if code != 0:
            self._temporary.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg exited with status {code}: {message}")
        os.replace(self._temporary, self.path)
        return self.path

    def __exit__(self, exception_type: Any, exception: Any, traceback: Any) -> bool:
        if exception_type is None:
            self.close()
        else:
            self.abort()
        return False
