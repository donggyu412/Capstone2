"""Normalized scene state; defaults are provisional, not measured values."""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from team4.DreamModel.config import DEFAULT_EMOTION_LABEL, DEFAULT_SCALAR, VECTOR_FIELDS


def clamp01(value: object, default: float = DEFAULT_SCALAR) -> float:
    """Accept finite numbers/numeric strings; reject booleans and invalid values."""
    try:
        if isinstance(value, (int, float, str)) and not isinstance(value, bool):
            number = float(value)
        else:
            number = float("nan")
    except (ValueError, OverflowError):
        number = float("nan")
    if not math.isfinite(number):
        number = default if math.isfinite(default) else DEFAULT_SCALAR
    return max(0.0, min(1.0, number))


def _emotion(scene: Mapping[str, object]) -> tuple[str, object]:
    raw = scene.get("main_emotion")
    fallback = scene.get("intensity", scene.get("emotion_intensity", DEFAULT_SCALAR))
    if isinstance(raw, Mapping):
        label = raw.get("label")
        intensity = raw.get("intensity", fallback)
    else:
        label, intensity = raw, fallback
    if not isinstance(label, str) or not label.strip():
        label = DEFAULT_EMOTION_LABEL
    return label, intensity


def _vector(scene: Mapping[str, object]) -> dict[str, float]:
    raw = scene.get("vector")
    values: dict[str, float] = {}
    for index, name in enumerate(VECTOR_FIELDS):
        component: object = DEFAULT_SCALAR
        if isinstance(raw, Mapping):
            component = raw.get(name, DEFAULT_SCALAR)
        elif isinstance(raw, (list, tuple)) and index < len(raw):
            component = raw[index]
        values[name] = clamp01(scene.get(name, component))
    return values


@dataclass(frozen=True)
class ReenactmentState:
    """One-based narrative position and normalized prototype controls."""

    scene_index: int
    narrative_stage: str
    emotion_label: str = DEFAULT_EMOTION_LABEL
    emotion_intensity: float = DEFAULT_SCALAR
    collective_response: float = DEFAULT_SCALAR
    tension: float = DEFAULT_SCALAR
    strangeness: float = DEFAULT_SCALAR
    density: float = DEFAULT_SCALAR
    temperature: float = DEFAULT_SCALAR

    def __post_init__(self) -> None:
        for name in ("emotion_intensity", "collective_response", *VECTOR_FIELDS):
            object.__setattr__(self, name, clamp01(getattr(self, name)))

    @classmethod
    def from_scene(
        cls, scene: Mapping[str, object], scene_index: int, narrative_stage: str
    ) -> "ReenactmentState":
        label, intensity = _emotion(scene)
        return cls(
            scene_index=scene_index,
            narrative_stage=narrative_stage,
            emotion_label=label,
            emotion_intensity=clamp01(intensity),
            collective_response=clamp01(scene.get("collective_response")),
            **_vector(scene),
        )

    def state_vector(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in VECTOR_FIELDS}
