"""Final renderer contract without a media backend or placeholder video files."""

from collections.abc import Iterable
from pathlib import Path


class FinalRenderer:
    """Future MP4 renderer and optional sound coupling entry point."""

    def render(
        self,
        frames: Iterable[object],
        output_path: Path,
        sound_path: Path | None = None,
    ) -> Path:
        """TODO: select frame format, encode MP4, and synchronize optional audio."""
        raise NotImplementedError("TODO: implement MP4 rendering and optional sound coupling.")
