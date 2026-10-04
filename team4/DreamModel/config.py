"""Small, provisional defaults for the interface / pipeline skeleton."""

from dataclasses import dataclass
from pathlib import Path

NARRATIVE_STAGES = ("기", "승", "전", "결")
VECTOR_FIELDS = ("tension", "strangeness", "density", "temperature")
DEFAULT_SCALAR = 0.5
DEFAULT_EMOTION_LABEL = "중립"
MODEL_NAME = "DreamModel"
MODEL_INPUT_ROOT = f"team4/input/{MODEL_NAME}Input"


@dataclass(frozen=True)
class PipelineConfig:
    """Resolve paths from this module, independently of the working directory."""

    repo_root: Path = Path(__file__).resolve().parents[2]
    seed: int = 42

    @property
    def model_dir(self) -> Path:
        return self.repo_root / "team4" / MODEL_NAME

    @property
    def input_dir(self) -> Path:
        return self.repo_root / MODEL_INPUT_ROOT

    @property
    def output_path(self) -> Path:
        return self.model_dir / "output" / "pipeline_plan.json"
