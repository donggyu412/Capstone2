"""Interface for a future background cellular automata state field."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from team4.DreamModel.models.state import ReenactmentState


@dataclass(frozen=True)
class BackgroundFrame:
    """Opaque background payload; pixel and state-grid formats are undecided."""

    payload: object


class BackgroundCAStateField:
    """Internal module name for future CA birth, survival and death rules."""

    def step(
        self,
        state: ReenactmentState,
        previous_frame: BackgroundFrame | None = None,
        *,
        asset_path: Path | None = None,
        parameters: Mapping[str, float] | None = None,
    ) -> BackgroundFrame:
        """TODO: define CA rules and generate a real background frame."""
        raise NotImplementedError(
            "TODO: implement background CA birth/survival/death rules and frame output."
        )
