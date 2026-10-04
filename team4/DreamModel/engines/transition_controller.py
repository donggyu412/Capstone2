"""Prototype threshold only; visual completion measurement remains TODO."""

from team4.DreamModel.models.state import clamp01


def prototype_transition_threshold(tension: float) -> float:
    """Return an unvalidated threshold, not a measured convergence score.

    Higher tension provisionally lowers the threshold from 0.85 to 0.60.
    TODO: define visual completion and validate actual scene-transition rules.
    """
    return clamp01(0.85 - 0.25 * clamp01(tension))
