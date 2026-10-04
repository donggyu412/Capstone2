"""Interface for future self-organizing swarm or particle dynamics."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from team4.DreamModel.models.state import ReenactmentState


@dataclass(frozen=True)
class ObjectSwarmSnapshot:
    """Opaque object-state payload; particle representation is undecided."""

    payload: object


class ObjectSwarm:
    """Internal module for future object decomposition, motion and reassembly."""

    def step(
        self,
        state: ReenactmentState,
        previous_snapshot: ObjectSwarmSnapshot | None = None,
        *,
        asset_paths: Sequence[Path] = (),
        parameters: Mapping[str, float] | None = None,
    ) -> ObjectSwarmSnapshot:
        """TODO: implement actual swarm/particle state updates and image output."""
        raise NotImplementedError(
            "TODO: implement self-organizing object swarm or particle dynamics."
        )
