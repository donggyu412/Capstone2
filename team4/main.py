"""Build a JSON pipeline plan; no image, video, or sound rendering is performed."""

import argparse
import io
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# Support both `python team4/main.py` and `python -m team4.main`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from team4.config import PipelineConfig
from team4.controllers.emotion_mapper import map_emotion_parameters
from team4.controllers.narrative_controller import NarrativeController
from team4.models.state import ReenactmentState
from team4.pipeline_io.adapters import (
    AssetInventory,
    discover_assets,
    display_path,
    load_story,
)


def _text_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _scene_plan(
    scene: dict[str, object], index: int, assets: AssetInventory, repo_root: Path
) -> dict[str, object]:
    stage = NarrativeController().stage_for_scene(index)
    state = ReenactmentState.from_scene(scene, index, stage)
    parameters = map_emotion_parameters(state)
    source_scene = scene.get("scene")
    return {
        "scene_index": index,
        "source_scene": source_scene if type(source_scene) in (str, int) else None,
        "narrative_stage": state.narrative_stage,
        "story": scene.get("story") if isinstance(scene.get("story"), str) else "",
        "backgrounds": _text_list(scene.get("backgrounds", scene.get("background"))),
        "objects": _text_list(scene.get("objects")),
        "physics_laws": _text_list(scene.get("physics_laws")),
        "emotion": state.emotion_label,
        "emotion_intensity": state.emotion_intensity,
        "collective_response": state.collective_response,
        "state_vector": state.state_vector(),
        "mapped_parameters": parameters,
        "background_asset_path": display_path(assets.backgrounds.get(index), repo_root),
        "object_asset_paths": [
            display_path(path, repo_root) for path in assets.objects.get(index, [])
        ],
        "planned_background_engine": {
            "module": "engines.background_ca", "status": "TODO",
            "mechanism": "Cellular Automata birth / survival / death",
        },
        "planned_object_engine": {
            "module": "engines.object_swarm", "status": "TODO",
            "mechanism": "self-organizing swarm / particles",
        },
        "planned_interaction": {
            "module": "engines.interaction", "status": "TODO",
            "mechanism": "background <-> object dynamics",
        },
        "planned_transition": {
            "module": "engines.transition_controller",
            "status": "prototype threshold only; completion measurement TODO",
            "threshold": parameters["transition_threshold"],
        },
    }


def build_pipeline_plan(
    config: PipelineConfig, input_path: Path | None = None
) -> dict[str, object]:
    """Read upstream data without modifying it and return a serializable plan."""
    story = load_story(config.repo_root, input_path)
    assets = discover_assets(config.repo_root)
    warnings = [*story.warnings, *assets.warnings]
    warnings.append("감정/상태 누락값은 임시 기본값(중립, 0.5)을 사용합니다. 매핑은 prototype mapping입니다.")
    return {
        "schema_version": 1,
        "stage": "Interface / Pipeline Skeleton Prototype",
        "rendered": False,
        "seed": config.seed,
        "seed_usage": "Reserved for future stochastic rules; this plan does not perturb values.",
        "source_path": display_path(story.path, config.repo_root),
        "warnings": warnings,
        "asset_inventory": {
            "backgrounds": {
                str(index): display_path(path, config.repo_root)
                for index, path in assets.backgrounds.items()
            },
            "object_directories": [
                display_path(path, config.repo_root) for path in assets.object_directories
            ],
            "shared_object_asset_paths": [
                display_path(path, config.repo_root) for path in assets.shared_objects
            ],
            "scene_manifest_paths": [
                display_path(path, config.repo_root) for path in assets.manifests
            ],
            "manifest_status": "discovery only; schema and scene associations require agreement",
        },
        "scenes": [
            _scene_plan(scene, index, assets, config.repo_root)
            for index, scene in enumerate(story.scenes, start=1)
        ],
    }


def write_pipeline_plan(config: PipelineConfig, plan: dict[str, object]) -> Path:
    """Write only the generated Team 4 plan. Reject non-finite JSON numbers."""
    content = json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_path.write_text(content, encoding="utf-8")
    return config.output_path


def main(argv: Sequence[str] | None = None) -> int:
    # Keep redirected Windows logs and JSON-related diagnostics in UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Team 4: 렌더링 전 파이프라인 계획 파일 생성")
    parser.add_argument("--input", type=Path, help="dream_scenes.json 지정 (상대경로는 현재 작업 폴더 기준)")
    parser.add_argument("--seed", type=int, default=42, help="향후 확률 규칙용 seed 메타데이터 (기본 42)")
    args = parser.parse_args(argv)
    config = PipelineConfig(seed=args.seed)
    plan = build_pipeline_plan(config, args.input)
    for warning in plan["warnings"]:
        print(f"[안내] {warning}")
    try:
        output_path = write_pipeline_plan(config, plan)
    except OSError as exc:
        print(f"[오류] Team 4 계획 파일을 저장하지 못했습니다: {exc}", file=sys.stderr)
        return 1
    print(f"[완료] {len(plan['scenes'])}개 장면의 계획: {output_path}")
    print("실제 프레임/MP4/사운드/영상 평가를 생성하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
