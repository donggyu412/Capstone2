"""Small end-to-end encodes and exact project timing, without upstream edits."""

from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np

from team4.DreamModel.config import RenderConfig
from team4.DreamModel.main import parse_config
# Archived 1.2 regression coverage. Active geometric pipeline has its own tests.
from team4.DreamModel.archive.formation_pipeline import render
from team4.DreamModel.tests import test_input_loader as fixtures


class RenderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.InputLoaderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        temporary = tempfile.TemporaryDirectory(prefix="dreammodel_render_")
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.config = RenderConfig(width=160, height=90, scene_seconds=0.4,
                                   transition_seconds=0.1, smoke=True,
                                   input_root=self.fixture.root,
                                   output_path=self.output / "preview.mp4",
                                   report_path=self.output / "report.json")

    def run_small_render(self, config=None, audio=None):
        with redirect_stdout(io.StringIO()):
            return render(config or self.config, audio)

    def test_final_cli_has_exact_project_spec_and_default_paths(self):
        config, audio = parse_config(["--final"])
        self.assertEqual((config.width, config.height, config.fps), (1920, 1080, 30))
        self.assertEqual((config.scene_frames, config.total_frames, config.duration), (2250, 9000, 300))
        self.assertEqual(config.output_path.name, "collective_dream_final.mp4")
        self.assertEqual(config.report_path.name, "collective_dream_final_report.json")
        self.assertIsNone(audio)
        smoke, _ = parse_config(["--smoke"])
        self.assertEqual((smoke.width, smoke.height, smoke.total_frames, smoke.duration), (640, 360, 600, 20))

    def test_real_video_report_and_persistent_scene_memory(self):
        report = self.run_small_render()
        self.assertTrue(self.config.output_path.is_file())
        self.assertEqual(json.loads(self.config.report_path.read_text(encoding="utf-8")), report)
        self.assertEqual(report["total_frames"], 48)
        self.assertEqual([s["stage"] for s in report["scenes"]], ["기", "승", "전", "결"])
        self.assertEqual([s["start_frame"] for s in report["scenes"]], [0, 12, 24, 36])
        self.assertEqual([s["transition_start_frame"] for s in report["scenes"]], [9, 21, 33, 45])
        for transfer in report["scene_memory_carryovers"]:
            self.assertGreater(transfer["before"], 0)
            self.assertAlmostEqual(transfer["after"] / transfer["before"], 0.35, places=6)
        self.assertEqual(report["audio"]["normalized_smoothed_peak"], 0)
        self.assertEqual(len(report["raw_frames_sha256"]), 64)

    def test_same_seed_same_frames_and_different_seed_changes_them(self):
        first = self.run_small_render()
        repeated = self.run_small_render()
        other = self.run_small_render(replace(self.config, seed=202))
        for key in ("state_sha256", "raw_frames_sha256"):
            self.assertEqual(first[key], repeated[key])
            self.assertNotEqual(first[key], other[key])

    def test_audio_changes_exploration_but_preserves_upstream_labels(self):
        path = self.output / "오디오_검증.wav"
        t = np.arange(16000 * 2) / 16000
        samples = (np.sin(2 * np.pi * 220 * t) * 10000).astype("<i2")
        with wave.open(str(path), "wb") as destination:
            destination.setnchannels(1)
            destination.setsampwidth(2)
            destination.setframerate(16000)
            destination.writeframes(samples.tobytes())
        silent = self.run_small_render()
        audible = self.run_small_render(audio=path)
        self.assertGreater(audible["audio"]["normalized_smoothed_peak"], 0.5)
        self.assertNotEqual(silent["mean_exploration_strength"], audible["mean_exploration_strength"])
        for before, after in zip(silent["scenes"], audible["scenes"]):
            for key in ("stage", "emotion_label", "emotion_intensity"):
                self.assertEqual(before[key], after[key])

    def test_output_cannot_replace_shared_input(self):
        with self.assertRaisesRegex(ValueError, "overwrite shared inputs"):
            replace(self.config, output_path=self.fixture.root / "overwrite.mp4")


if __name__ == "__main__":
    unittest.main()
