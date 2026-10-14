"""Input-contract tests use temporary fixtures, never edit upstream assets."""

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from PIL import Image

from team4.DreamModel.input_loader import load_inputs


class InputLoaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dreammodel_inputs_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storyboard = self.root / "storyboard"
        self.objects = self.root / "objects"
        self.storyboard.mkdir()
        self.objects.mkdir()
        self.meta = {"scenes": []}
        self.dream = {"scenes": []}
        self.object_manifest = {"scenes": []}
        for number, stage in enumerate(("기", "승", "전", "결"), start=1):
            image_name = f"scene_{number:02d}.png"
            Image.new("RGB", (64, 36), (30, 50, 70)).save(self.storyboard / image_name)
            names = [f"낡은 항해일지 {number}", f"푸른빛 그림자 {number}"]
            entries = []
            for index, name in enumerate(names, start=1):
                relative = f"scene_{number:02d}/obj_{index}_{name.replace(' ', '_')}.png"
                path = self.objects / relative
                path.parent.mkdir(exist_ok=True)
                image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
                image.paste((90, 140, 190, 255), (128, 128, 384, 384))
                image.save(path)
                entries.append({"index": index, "name_ko": name, "file": relative})
            self.meta["scenes"].append({"act": number, "stage": stage, "title": f"장면 {number}", "emotion": "공포", "intensity": 0.8, "files": {"background": image_name, "with_title": "absent.png"}, "source_image": "/media/ignored.png"})
            self.dream["scenes"].append({"scene": number, "story": f"기억 속 장면 {number}", "objects": names, "main_emotion": {"label": "공포", "intensity": 0.8}, "vector": [0.1, 0.2, 0.3, 0.4]})
            self.object_manifest["scenes"].append({"scene": number, "objects": entries})
        self.write_manifests()

    def write_manifests(self):
        for path, value in [(self.storyboard / "scenes.json", self.meta), (self.storyboard / "dream_scenes.json", self.dream), (self.objects / "objects.json", self.object_manifest)]:
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8-sig")

    def test_actual_contract_and_korean_filenames(self):
        bundle = load_inputs(self.root)
        self.assertEqual([scene.stage for scene in bundle.scenes], ["기", "승", "전", "결"])
        self.assertEqual(bundle.scenes[0].objects[0].object_id, "1:1")
        self.assertIn("낡은_항해일지", bundle.scenes[0].objects[0].path.name)
        self.assertEqual(len(bundle.input_files), 3 + 4 + 8)
        self.assertIsNone(bundle.audio_path)
        self.assertTrue(any("silent" in warning for warning in bundle.warnings))
        with self.assertRaises(FrozenInstanceError):
            bundle.scenes[0].stage = "결"

    def test_metadata_order_is_preserved(self):
        self.meta["scenes"] = self.meta["scenes"][::-1]
        self.write_manifests()
        self.assertEqual([scene.scene_id for scene in load_inputs(self.root).scenes], [4, 3, 2, 1])

    def test_unused_upstream_fields_cannot_change_loaded_state(self):
        before = load_inputs(self.root)
        for scene in self.dream["scenes"]:
            scene["vector"] = [999, -200, 888, None]
            scene.update(tension=999, strangeness=-100, density=30, temperature="unused")
        self.write_manifests()
        self.assertEqual(before, load_inputs(self.root))

    def test_missing_or_invalid_stage_is_not_inferred(self):
        for stage in (None, "unknown", 0.4):
            with self.subTest(stage=stage):
                self.meta["scenes"][0]["stage"] = stage
                self.write_manifests()
                with self.assertRaisesRegex(ValueError, "upstream stage"):
                    load_inputs(self.root)

    def test_duplicate_and_mismatched_scene_ids(self):
        self.dream["scenes"][1]["scene"] = 1
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "duplicate scene ID"):
            load_inputs(self.root)
        self.dream["scenes"][1]["scene"] = 5
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "Scene IDs must match"):
            load_inputs(self.root)

    def test_path_escape_or_absolute_path_is_rejected(self):
        for reference in ("../../outside.png", "C:\\outside.png", "/outside.png"):
            with self.subTest(reference=reference):
                self.object_manifest["scenes"][0]["objects"][0]["file"] = reference
                self.write_manifests()
                with self.assertRaises(ValueError):
                    load_inputs(self.root)

    def test_missing_asset_and_no_guessed_filenames(self):
        self.meta["scenes"][0]["files"]["background"] = "missing.png"
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "does not exist"):
            load_inputs(self.root)

    def test_emotion_conflict_is_reported(self):
        self.dream["scenes"][0]["main_emotion"]["intensity"] = 0.3
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "emotion/intensity conflict"):
            load_inputs(self.root)

    def test_object_name_order_conflict_is_reported(self):
        self.dream["scenes"][0]["objects"].reverse()
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "object name/order conflict"):
            load_inputs(self.root)

    def test_alpha_channel_is_required(self):
        path = self.objects / self.object_manifest["scenes"][0]["objects"][0]["file"]
        Image.new("RGB", (512, 512)).save(path)
        with self.assertRaisesRegex(ValueError, "RGBA PNG"):
            load_inputs(self.root)

    def test_unique_audio_discovery_and_explicit_choice(self):
        first = self.root / "사운드.wav"
        first.write_bytes(b"audio decoding belongs to audio_analyzer")
        self.assertEqual(load_inputs(self.root).audio_path, first.resolve())
        second = self.root / "other.mp3"
        second.write_bytes(b"audio")
        with self.assertRaisesRegex(ValueError, "--audio"):
            load_inputs(self.root)
        self.assertEqual(load_inputs(self.root, second).audio_path, second.resolve())

    def test_manifest_audio_reference(self):
        audio = self.root / "shared.wav"
        audio.write_bytes(b"audio")
        (self.root / "unused.mp3").write_bytes(b"audio")
        self.meta["audio"] = {"file": "../shared.wav"}
        self.write_manifests()
        self.assertEqual(load_inputs(self.root).audio_path, audio.resolve())

    def test_distinct_scene_audio_not_silently_combined(self):
        for number in (1, 2):
            name = f"part{number}.wav"
            (self.storyboard / name).write_bytes(b"audio")
            self.meta["scenes"][number - 1]["audio"] = name
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "per-scene audio"):
            load_inputs(self.root)


if __name__ == "__main__":
    unittest.main()
