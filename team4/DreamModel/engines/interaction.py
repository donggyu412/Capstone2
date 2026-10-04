"""Interface for future two-way background and object interaction."""

from dataclasses import dataclass

from team4.DreamModel.engines.background_ca import BackgroundFrame
from team4.DreamModel.engines.object_swarm import ObjectSwarmSnapshot
from team4.DreamModel.models.state import ReenactmentState


@dataclass(frozen=True)
class CoupledSnapshot:
    """Contract for the eventual outputs of a coupled dynamics update."""

    background: BackgroundFrame
    objects: ObjectSwarmSnapshot


class CoupledDynamics:
    """Internal module name; no interaction algorithm is implemented yet."""

    def step(
        self,
        state: ReenactmentState,
        background: BackgroundFrame,
        objects: ObjectSwarmSnapshot,
    ) -> CoupledSnapshot:
        """TODO: apply background-to-object and object-to-background feedback."""
        raise NotImplementedError(
            "TODO: implement bidirectional background/object interaction."
        )
