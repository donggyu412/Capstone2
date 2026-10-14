"""Public aggregate audience conditions; defaults are not measured spectators."""
from dataclasses import dataclass,asdict
import math


@dataclass(frozen=True)
class AudienceAtmosphere:
    arousal: float = .5
    tension: float = .5
    coherence: float = .5
    source: str = 'preview defaults; no measured audience aggregate supplied'

    def __post_init__(self):
        for key in ('arousal','tension','coherence'):
            value=getattr(self,key)
            if not math.isfinite(value) or not 0<=value<=1:
                raise ValueError(f'Audience {key} must be finite and between 0 and 1')

    def report(self):return asdict(self)
