"""Interfaces only: no novelty, diversity or recognizability scores exist yet."""

from collections.abc import Iterable
from pathlib import Path


def novelty(frames: Iterable[object], reference_frames: Iterable[object]) -> float:
    """TODO: define a representation, reference set and novelty measure."""
    raise NotImplementedError("TODO: implement and validate real video novelty evaluation.")


def diversity(frames: Iterable[object]) -> float:
    """TODO: define a meaningful diversity metric over actual generated frames."""
    raise NotImplementedError("TODO: implement and validate real video diversity evaluation.")


def recognizability(frames: Iterable[object], reference_assets: Iterable[Path]) -> float:
    """TODO: evaluate whether source objects remain recognizable in a video."""
    raise NotImplementedError(
        "TODO: implement and validate real video recognizability evaluation."
    )
