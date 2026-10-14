"""Route upstream narrative labels to mechanisms only in the final window."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class TransitionMode(str, Enum):
    EMERGENCE = "EMERGENCE"
    ACCUMULATION = "ACCUMULATION"
    FRAGMENTATION = "FRAGMENTATION"
    DISSOLUTION = "DISSOLUTION"


def mode_for_stage(stage: str) -> TransitionMode:
    """Literal routing, never infer a stage from a scene id or other values."""
    modes = {
        "기": TransitionMode.EMERGENCE,
        "승": TransitionMode.ACCUMULATION,
        "전": TransitionMode.FRAGMENTATION,
        "결": TransitionMode.DISSOLUTION,
    }
    if not isinstance(stage, str) or stage not in modes:
        raise ValueError(f"Unknown upstream stage {stage!r}; expected 기, 승, 전, or 결")
    return modes[stage]


@dataclass(frozen=True)
class TransitionState:
    mode: TransitionMode
    progress: float

    def __post_init__(self) -> None:
        if not isinstance(self.mode, TransitionMode):
            raise ValueError("transition mode must be a TransitionMode")
        if not math.isfinite(self.progress) or not 0 <= self.progress <= 1:
            raise ValueError("transition progress must be in [0, 1]")

    @property
    def smooth_progress(self) -> float:
        return self.progress * self.progress * (3 - 2 * self.progress)

    @property
    def background_mix(self) -> float:
        return self.smooth_progress


class TransitionController:
    def __init__(self, window_seconds: float = 2.0) -> None:
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("transition window must be finite and positive")
        self.window_seconds = window_seconds

    def state_for_frame(
        self, stage: str, frame_index: int, total_frames: int, fps: int,
    ) -> TransitionState | None:
        """Use exactly the final N frames, including both window endpoints.

        Frame indices are zero based. The first included frame has progress
        zero and the last frame has progress one; a one-frame window completes
        immediately. This avoids shifting the window one frame early by using
        a frame-end timestamp for a frame-start index.
        """
        mode = mode_for_stage(stage)
        if type(fps) is not int or fps <= 0:
            raise ValueError("fps must be a positive integer")
        if type(total_frames) is not int or total_frames <= 0:
            raise ValueError("total frames must be a positive integer")
        if type(frame_index) is not int or not 0 <= frame_index < total_frames:
            raise ValueError("frame index must be within this scene")
        window_frames = min(total_frames, max(1, round(self.window_seconds * fps)))
        start = total_frames - window_frames
        if frame_index < start:
            return None
        progress = (frame_index - start) / (window_frames - 1) if window_frames > 1 else 1.0
        return TransitionState(mode, progress)

    def state(
        self, stage: str, elapsed_seconds: float, duration_seconds: float,
    ) -> TransitionState | None:
        mode = mode_for_stage(stage)
        if not math.isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("scene duration must be finite and positive")
        if not math.isfinite(elapsed_seconds) or not 0 <= elapsed_seconds <= duration_seconds:
            raise ValueError("elapsed time must be within this scene")
        window = min(self.window_seconds, duration_seconds)
        start = duration_seconds - window
        if elapsed_seconds < start:
            return None
        return TransitionState(mode, min(1.0, (elapsed_seconds - start) / window))
