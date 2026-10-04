"""Isolated standard-library checks; upstream team directories are never changed."""

import importlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterable
from pathlib import Path

from team4.config import PipelineConfig
from team4.controllers.emotion_mapper import map_emotion_parameters
from team4.controllers.narrative_controller import NarrativeController
from team4.engines.background_ca import BackgroundCAStateField
from team4.engines.stochastic_rules import StochasticRuleModulator
from team4.engines.temporal_memory import TemporalMemory
from team4.main import build_pipeline_plan, write_pipeline_plan
from team4.models.state import ReenactmentState, clamp01
from team4.pipeline_io.adapters import discover_assets, load_story
from team4.renderer.final_renderer import FinalRenderer

TEAM4 = Path(__file__).resolve().parents[1]


class PipelineSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Even miniature upstream fixtures stay under Team 4's generated output.
        output = TEAM4 / "output"
        output.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="smoke_", dir=output)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = PipelineConfig(repo_root=self.root)

    def write_json(self, relative: str, payload: object) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def assert_unit_interval(self, values: Iterable[float]) -> None:
        for value in values:
            self.assertTrue(math.isfinite(value))
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_all_modules_import_without_optional_dependencies(self) -> None:
        for path in TEAM4.rglob("*.py"):
            relative = path.relative_to(TEAM4)
            if relative.parts[0] in {"tests", "output"}:
                continue
            parts = ("team4", *relative.with_suffix("").parts)
            with self.subTest(module=".".join(parts)):
                importlib.import_module(".".join(parts))

    def test_missing_inputs_create_empty_plan_with_warnings(self) -> None:
        plan = build_pipeline_plan(self.config)
        output = write_pipeline_plan(self.config, plan)
        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["scenes"], [])
        self.assertIsNone(saved["source_path"])
        self.assertTrue(saved["warnings"])
        self.assertFalse(saved["rendered"])

    def test_observed_team2_schema_generates_four_scene_plan(self) -> None:
        scenes = [
            {"scene": index, "story": "꿈의 장면", "backgrounds": ["숲"],
             "objects": ["나비"], "physics_laws": ["중력 반전"],
             "main_emotion": {"label": "기쁨", "intensity": 0.8},
             "vector": [0.2, 0.3, 0.4, 0.5]}
            for index in range(1, 5)
        ]
        source = self.write_json("team2/output/dream_scenes.json", {"scenes": scenes})
        before = source.read_bytes()
        plan = build_pipeline_plan(self.config)
        output = write_pipeline_plan(self.config, plan)
        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual([scene["narrative_stage"] for scene in saved["scenes"]], ["기", "승", "전", "결"])
        self.assertEqual(saved["source_path"], "team2/output/dream_scenes.json")
        for scene in saved["scenes"]:
            self.assertEqual(scene["emotion"], "기쁨")
            self.assertEqual(scene["emotion_intensity"], 0.8)
            self.assertEqual(scene["state_vector"]["tension"], 0.2)
            self.assertEqual(scene["objects"], ["나비"])
            self.assertIsNone(scene["background_asset_path"])
            self.assertEqual(scene["object_asset_paths"], [])
            self.assert_unit_interval(scene["mapped_parameters"].values())
        self.assertEqual(source.read_bytes(), before)

    def test_malformed_json_and_wrong_root_are_nonfatal(self) -> None:
        path = self.root / "dream_scenes.json"
        for content in (b"{broken", b"\xff", b"null", b'{"scenes": {}}'):
            with self.subTest(content=content):
                path.write_bytes(content)
                plan = build_pipeline_plan(self.config, path)
                write_pipeline_plan(self.config, plan)
                self.assertEqual(plan["scenes"], [])
                self.assertTrue(plan["warnings"])

    def test_scene_slots_are_preserved_without_inventing_missing_scenes(self) -> None:
        path = self.write_json("team4/input/dream_scenes.json", [None, {}, {}, {}, {}])
        story = load_story(self.root)
        self.assertEqual(story.path, path)
        self.assertEqual(len(story.scenes), 4)
        self.assertEqual(story.scenes[0], {})
        self.assertTrue(story.warnings)
        self.write_json("team4/input/dream_scenes.json", {"scenes": [{}]})
        self.assertEqual(len(build_pipeline_plan(self.config)["scenes"]), 1)

    def test_invalid_numeric_fields_never_leak_nonfinite_values(self) -> None:
        for value in (-50, 50, "0.25", None, True, [], {}, "invalid", "nan", float("inf"), float("nan"), 10**400):
            with self.subTest(value=repr(value)):
                state = ReenactmentState.from_scene(
                    {"intensity": value, "collective_response": value, "vector": [value] * 4}, 1, "기"
                )
                values = [state.emotion_intensity, state.collective_response, *state.state_vector().values()]
                self.assert_unit_interval(values)
                mapped = map_emotion_parameters(state)
                self.assert_unit_interval(mapped.values())
                json.dumps(mapped, allow_nan=False)
        self.assertEqual(clamp01(None), 0.5)
        self.assertEqual(clamp01(-1), 0)
        self.assertEqual(clamp01(2), 1)

    def test_flat_emotion_named_vector_and_background_alias(self) -> None:
        self.write_json("team2/dream_scenes.json", [{
            "main_emotion": "놀람", "intensity": "0.9", "background": "바다",
            "vector": {"tension": 0.1}, "temperature": 0.8,
        }])
        scene = build_pipeline_plan(self.config)["scenes"][0]
        self.assertEqual(scene["emotion"], "놀람")
        self.assertEqual(scene["emotion_intensity"], 0.9)
        self.assertEqual(scene["backgrounds"], ["바다"])
        self.assertEqual(scene["state_vector"], {"tension": 0.1, "strangeness": 0.5, "density": 0.5, "temperature": 0.8})

    def test_asset_discovery_does_not_guess_shared_object_scene(self) -> None:
        paths = ["team3/output/scene_01.png", "team3/input/scene_01.png",
                 "team3/output/objects/scene_01/butterfly.png",
                 "team3/output/objects/shared.png", "team3/output/scenes.json"]
        for relative in paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"path-only discovery fixture")
        before = {relative: (self.root / relative).read_bytes() for relative in paths}
        assets = discover_assets(self.root)
        self.assertEqual(assets.backgrounds[1], self.root / paths[0])
        self.assertEqual(assets.objects[1], [self.root / paths[2]])
        self.assertEqual(assets.shared_objects, [self.root / paths[3]])
        self.assertEqual(assets.manifests, [self.root / paths[4]])
        self.assertNotIn(2, assets.objects)
        self.assertEqual(len(assets.object_directories), 1)
        self.assertEqual(before, {relative: (self.root / relative).read_bytes() for relative in paths})

    def test_explicit_missing_input_does_not_silently_choose_another_story(self) -> None:
        self.write_json("team2/dream_scenes.json", [{}, {}, {}, {}])
        story = load_story(self.root, self.root / "missing.json")
        self.assertEqual(story.scenes, [])
        self.assertTrue(story.warnings)

    def test_cli_from_another_working_directory_with_relative_input(self) -> None:
        shutil.copytree(TEAM4, self.root / "team4", ignore=shutil.ignore_patterns("output", "__pycache__", "tests"))
        self.write_json("input/story.json", {"scenes": [{}, {}, {}, {}]})
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        command = [sys.executable, str(self.root / "team4/main.py"), "--input", "../input/story.json"]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(command, cwd=elsewhere, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads(self.config.output_path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["scenes"]), 4)
        self.assertFalse((elsewhere / "output").exists())
        result = subprocess.run(command[:-1] + ["missing.json"], cwd=elsewhere, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.config.output_path.read_text(encoding="utf-8"))["scenes"], [])

    def test_memory_and_seeded_variation(self) -> None:
        state = ReenactmentState(1, "기")
        memory = TemporalMemory()
        self.assertIsNone(memory.snapshot())
        memory.save(state)
        self.assertEqual(memory.snapshot(), state)
        memory.clear()
        self.assertIsNone(memory.snapshot())
        first, second = StochasticRuleModulator(seed=9), StochasticRuleModulator(seed=9)
        values = [first.perturb(0.5) for _ in range(8)]
        self.assertEqual(values, [second.perturb(0.5) for _ in range(8)])
        self.assert_unit_interval(values)

    def test_unimplemented_rendering_is_explicit(self) -> None:
        with self.assertRaises(NotImplementedError):
            BackgroundCAStateField().step(ReenactmentState(1, "기"))
        output = self.root / "video.mp4"
        with self.assertRaises(NotImplementedError):
            FinalRenderer().render([], output)
        self.assertFalse(output.exists())
        with self.assertRaises(ValueError):
            NarrativeController().stage_for_scene(0)


if __name__ == "__main__":
    unittest.main()
