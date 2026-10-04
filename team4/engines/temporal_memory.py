"""Minimal memory of the previous immutable scene state."""

from dataclasses import dataclass, field

from team4.models.state import ReenactmentState


@dataclass
class TemporalMemory:
    """Store one state; frame history and temporal feedback rules remain TODO."""

    _previous_state: ReenactmentState | None = field(default=None, init=False, repr=False)

    def save(self, state: ReenactmentState) -> None:
        """Replace the previous state with an immutable ReenactmentState."""
        self._previous_state = state

    def snapshot(self) -> ReenactmentState | None:
        """Return the saved immutable state, or None before the first save."""
        return self._previous_state

    def clear(self) -> None:
        """Forget the previous state before starting another sequence."""
        self._previous_state = None
