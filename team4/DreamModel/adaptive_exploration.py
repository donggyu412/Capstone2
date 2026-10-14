"""Activity feedback regulates exploration, with optional audio RMS input."""

from __future__ import annotations

import math


class AdaptiveExploration:
    """Bounded feedback controller; keep this instance across scene changes."""

    def __init__(
        self,
        target_activity: float = 0.32,
        initial_strength: float = 0.00025,
        min_strength: float = 0.00004,
        max_strength: float = 0.0008,
        learning_rate: float = 0.00002,
        audio_gain: float = 0.000003,
        smoothing: float = 0.12,
    ) -> None:
        values = (
            target_activity, initial_strength, min_strength, max_strength,
            learning_rate, audio_gain, smoothing,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("exploration settings must be finite")
        if not 0 <= target_activity <= 1 or not 0 < smoothing <= 1:
            raise ValueError("activity target and smoothing must be normalized")
        if not 0 <= min_strength <= initial_strength <= max_strength:
            raise ValueError("require 0 <= minimum <= initial <= maximum")
        if learning_rate < 0 or audio_gain < 0:
            raise ValueError("exploration gains cannot be negative")
        self.target_activity = target_activity
        self.strength = initial_strength
        self.min_strength, self.max_strength = min_strength, max_strength
        self.learning_rate, self.audio_gain = learning_rate, audio_gain
        self.smoothing = smoothing
        self.smoothed_activity = target_activity
        self.smoothed_audio = 0.0

    def update(self, activity: float, audio_rms: float = 0.0) -> float:
        if not math.isfinite(activity) or not math.isfinite(audio_rms):
            raise ValueError("activity and audio RMS must be finite")
        activity = min(1.0, max(0.0, activity))
        audio_rms = min(1.0, max(0.0, audio_rms))
        self.smoothed_activity += self.smoothing * (activity - self.smoothed_activity)
        self.smoothed_audio += self.smoothing * (audio_rms - self.smoothed_audio)
        # Project formula 3: sigma' = clip(sigma + eta*(target-A) + kappa*R).
        updated = (
            self.strength
            + self.learning_rate * (self.target_activity - self.smoothed_activity)
            + self.audio_gain * self.smoothed_audio
        )
        self.strength = min(self.max_strength, max(self.min_strength, updated))
        return self.strength
