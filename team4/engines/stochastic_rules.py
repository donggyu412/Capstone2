"""Small reproducible parameter variations, not a video generation algorithm."""

from dataclasses import dataclass, field
import random

from team4.models.state import clamp01


@dataclass
class StochasticRuleModulator:
    """Add uniform prototype noise using an instance-local random generator."""

    seed: int = 42
    amplitude: float = 0.05
    _random: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.amplitude = clamp01(self.amplitude, default=0.05)
        self._random = random.Random(self.seed)

    def perturb(self, value: float) -> float:
        """Normalize a value, vary it by at most amplitude, and clamp to 0..1."""
        amplitude = clamp01(self.amplitude, default=0.05)
        return clamp01(clamp01(value) + self._random.uniform(-amplitude, amplitude))

    def reset(self) -> None:
        """Restart the local sequence with the configured seed."""
        self._random.seed(self.seed)
