"""Prototype mapping only: these formulas have not been scientifically validated."""

from team4.DreamModel.engines.transition_controller import prototype_transition_threshold
from team4.DreamModel.models.state import ReenactmentState, clamp01


def map_emotion_parameters(state: ReenactmentState) -> dict[str, float]:
    """Map normalized numeric inputs; label-specific calibration remains TODO."""
    intensity = state.emotion_intensity
    collective = state.collective_response
    parameters = {
        "ca_activity": intensity,
        "ca_birth_bias": (state.tension + state.temperature) / 2,
        "object_speed": (intensity + state.tension) / 2,
        "object_cohesion": (collective + 1 - state.density) / 2,
        "object_dispersion": (state.strangeness + state.density) / 2,
        "stochasticity": (state.strangeness + 1 - collective) / 2,
        "transition_threshold": prototype_transition_threshold(state.tension),
    }
    return {name: clamp01(value) for name, value in parameters.items()}
