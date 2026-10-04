"""Internal scene-order controller, not a named research algorithm."""

from team4.DreamModel.config import NARRATIVE_STAGES


class NarrativeController:
    """Map scene positions 1..4 to 기 / 승 / 전 / 결."""

    def stage_for_scene(self, scene_index: int) -> str:
        if isinstance(scene_index, bool) or not isinstance(scene_index, int):
            raise ValueError("scene_index must be an integer from 1 to 4")
        if not 1 <= scene_index <= len(NARRATIVE_STAGES):
            raise ValueError("scene_index must be from 1 to 4")
        return NARRATIVE_STAGES[scene_index - 1]
