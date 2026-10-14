"""Small real media checks; no five-minute render is required by the tests."""

from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import wave

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from team4.DreamModel.runtime.audio_analyzer import AudioAnalyzer
from team4.DreamModel.archive.frame_renderer import FrameRenderer, VideoWriter, find_ffmpeg, load_background, load_sprite, subprocess_options


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(np.int16(np.clip(samples, -1, 1) * 32767).tobytes())


def agent(x: float = .5, opacity: float = .7) -> SimpleNamespace:
    return SimpleNamespace(position=np.array([x, .5]), scale=1., rotation=13., opacity=opacity, seed=101)


class CompositorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.background = np.full((72, 128, 3), 22, dtype=np.uint8)
        self.sprite = np.full((32, 32, 4), 225, dtype=np.uint8)
        self.sprite[..., 3] = 0
        self.sprite[4:28, 4:28, 3] = 200
        self.trace = np.zeros((9, 16), dtype=np.float32)

    def test_unicode_assets_preserve_alpha_and_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="꿈_") as directory:
            path = Path(directory) / "obj_1_낡은_항해일지.png"
            Image.fromarray(self.sprite).save(path)
            np.testing.assert_array_equal(load_sprite(path), self.sprite)
            self.assertEqual(load_background(path, 128, 72).shape, self.background.shape)
            self.assertTrue(path.exists())

    def test_same_state_sequence_is_pixel_reproducible(self) -> None:
        renderers = [FrameRenderer(128, 72), FrameRenderer(128, 72)]
        agents = [agent(.2), agent(.2)]
        for frame in range(20):
            results = []
            for renderer, current in zip(renderers, agents):
                current.position[0] = .2 + frame * .02
                current.rotation = frame * 2
                results.append(renderer.render(self.background, [self.sprite], [current], self.trace))
            np.testing.assert_array_equal(*results)
        self.assertFalse(np.array_equal(results[0], self.background))
        self.assertTrue(np.all(self.background == 22))

    def test_transparent_sprite_does_not_paint_background(self) -> None:
        self.sprite[..., 3] = 0
        actual = FrameRenderer(128, 72).render(self.background, [self.sprite], [agent()], self.trace)
        np.testing.assert_array_equal(actual, self.background)

    def test_trace_is_visible_even_without_current_objects(self) -> None:
        self.trace[4, 7] = 1
        actual = FrameRenderer(128, 72).render(self.background, [], [], self.trace)
        self.assertGreater(int(actual.sum()), int(self.background.sum()))

    def test_ghost_survives_agent_change_then_decays(self) -> None:
        renderer = FrameRenderer(128, 72)
        current = agent()
        renderer.render(self.background, [self.sprite], [current], self.trace)
        retained = renderer.render(self.background, [], [], self.trace)
        self.assertFalse(np.array_equal(retained, self.background))
        for _ in range(20):
            final = renderer.render(self.background, [], [], self.trace)
        np.testing.assert_array_equal(final, self.background)

    def test_transition_is_local_in_time_and_depends_on_memory(self) -> None:
        next_background = self.background + 75
        renderer = FrameRenderer(128, 72)
        no_window = renderer.render(self.background, [], [], self.trace, next_background=next_background)
        np.testing.assert_array_equal(no_window, self.background)
        transition = SimpleNamespace(mode="ACCUMULATION", progress=.5)
        empty = renderer.render(self.background, [], [], self.trace, transition=transition,
                                next_background=next_background)
        self.trace[2:6, 4:9] = 2
        memory = renderer.render(self.background, [], [], self.trace, transition=transition,
                                 next_background=next_background)
        self.assertFalse(np.array_equal(empty, memory))

    def test_final_dissolution_ends_at_black(self) -> None:
        actual = FrameRenderer(128, 72).render(self.background, [self.sprite], [agent()], self.trace,
                    transition=SimpleNamespace(mode="DISSOLUTION", progress=1.))
        self.assertFalse(actual.any())

    def test_outgoing_bodies_and_ghosts_do_not_pop_at_scene_boundary(self) -> None:
        for mode in ("EMERGENCE", "ACCUMULATION", "FRAGMENTATION"):
            with self.subTest(mode=mode):
                renderer = FrameRenderer(128, 72)
                outgoing, incoming = agent(.25), agent(.75)
                next_background = self.background + 12
                for frame in range(20):
                    outgoing.position[0] = .20 + .003 * frame
                    renderer.render(self.background, [self.sprite], [outgoing], self.trace)
                # Move the outgoing object so ghosts occupy visibly different
                # pixels. They must obey the same fade as its current body.
                outgoing.position[0] = .4
                for progress in (.25, .5, .75, .95, 1.):
                    end = renderer.render(
                        self.background, [self.sprite], [outgoing], self.trace,
                        transition=SimpleNamespace(mode=mode, progress=progress),
                        next_background=next_background, next_sprites=[self.sprite],
                        next_agents=[incoming],
                    )
                following = renderer.render(next_background, [self.sprite], [incoming], self.trace)
                # No simulation movement here: any difference would be a
                # boundary-only compositing jump, not new agent dynamics.
                np.testing.assert_array_equal(end, following)
                self.assertIn(id(outgoing), renderer._history)
                self.assertEqual(renderer._last_visibility[id(outgoing)], 0)

    def test_fragmentation_changes_actual_current_sprite(self) -> None:
        current = agent()
        normal = FrameRenderer(128, 72).render(self.background, [self.sprite], [current], self.trace)
        split = FrameRenderer(128, 72).render(self.background, [self.sprite], [current], self.trace,
                    transition=SimpleNamespace(mode="FRAGMENTATION", progress=.55))
        self.assertFalse(np.array_equal(normal, split))

    def test_accumulation_visibly_keeps_more_of_both_intact_objects(self) -> None:
        frames = []
        for mode in ("EMERGENCE", "ACCUMULATION"):
            frames.append(FrameRenderer(128, 72).render(
                self.background, [self.sprite], [agent(.25, .9)], self.trace,
                transition=SimpleNamespace(mode=mode, progress=.5),
                next_background=self.background, next_sprites=[self.sprite],
                next_agents=[agent(.75, .9)],
            ))
        self.assertGreater(int(frames[1].sum()), int(frames[0].sum()) * 1.15)


class AudioAndVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffmpeg = find_ffmpeg()

    def test_optional_missing_audio_is_zero(self) -> None:
        audio = AudioAnalyzer()
        self.assertEqual([audio.sample(t) for t in (0, 50, 299)], [0, 0, 0])
        self.assertIsNone(audio.as_report()["path"])

    def test_supplied_missing_or_malformed_audio_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "absent.wav"
            with self.assertRaises(FileNotFoundError):
                AudioAnalyzer(path)
            path.write_text("not audio", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Cannot decode"):
                AudioAnalyzer(path)

    def test_real_audio_spike_is_normalized_smoothed_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="꿈_") as directory:
            path = Path(directory) / "소리.wav"
            samples = np.zeros(16000, dtype=np.float32)
            samples[4000:6400] = .5 * np.sin(np.arange(2400) * 2 * np.pi * 440 / 16000)
            write_wav(path, samples)
            audio = AudioAnalyzer(path, smoothing_seconds=.1)
            repeated = AudioAnalyzer(path, smoothing_seconds=.1)
            self.assertAlmostEqual(audio.duration, 1)
            self.assertEqual(audio.sample(.1), 0)
            self.assertGreater(audio.sample(.38), .5)
            self.assertGreater(audio.sample(.45), 0)
            self.assertLess(audio.sample(.75), audio.sample(.45))
            self.assertEqual(audio.sample(1), 0)
            self.assertTrue(np.all((audio.values >= 0) & (audio.values <= 1)))
            np.testing.assert_array_equal(audio.values, repeated.values)

    def test_actual_silence_stays_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silence.wav"
            write_wav(path, np.zeros(8000))
            audio = AudioAnalyzer(path)
            self.assertFalse(audio.values.any())

    def test_streamed_unicode_mp4_has_exact_frames_and_real_h264(self) -> None:
        with tempfile.TemporaryDirectory(prefix="꿈_") as directory:
            path = Path(directory) / "미리보기.mp4"
            with VideoWriter(path, 32, 24, 12, expected_frames=12) as writer:
                for value in range(12):
                    frame = np.full((24, 32, 3), value * 15, dtype=np.uint8)
                    writer.write(frame)
            result = subprocess.run([self.ffmpeg, "-hide_banner", "-i", str(path),
                                     "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True,
                                    **subprocess_options())
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(result.stdout), 12 * 32 * 24 * 3)
            metadata = result.stderr.decode("utf-8", errors="replace")
            self.assertIn("h264", metadata)
            self.assertIn("yuv420p", metadata)
            self.assertIn("Duration: 00:00:01.00", metadata)

    def test_short_audio_is_muxed_and_padded_to_video_length(self) -> None:
        with tempfile.TemporaryDirectory(prefix="꿈_") as directory:
            path, sound = Path(directory) / "소리영상.mp4", Path(directory) / "짧은소리.wav"
            write_wav(sound, .3 * np.sin(np.arange(3200) * 2 * np.pi * 440 / 16000))
            with VideoWriter(path, 32, 24, 12, audio_path=sound, expected_frames=12) as writer:
                for _ in range(12):
                    writer.write(np.full((24, 32, 3), 77, dtype=np.uint8))
            result = subprocess.run([self.ffmpeg, "-hide_banner", "-i", str(path), "-map", "0:a:0",
                                     "-ar", "16000", "-ac", "1", "-f", "f32le", "pipe:1"], capture_output=True,
                                    **subprocess_options())
            self.assertEqual(result.returncode, 0)
            samples = np.frombuffer(result.stdout, dtype="<f4")
            self.assertGreaterEqual(samples.size, 16000)
            self.assertGreater(float(np.max(np.abs(samples[:3200]))), .1)
            self.assertLess(float(np.max(np.abs(samples[12000:16000]))), .001)
            self.assertIn("Duration: 00:00:01.00", result.stderr.decode("utf-8", errors="replace"))

    def test_incomplete_encode_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preserved.mp4"
            path.write_bytes(b"existing file")
            with self.assertRaisesRegex(ValueError, "frame count"):
                with VideoWriter(path, 32, 24, 12, expected_frames=12) as writer:
                    writer.write(np.zeros((24, 32, 3), dtype=np.uint8))
            self.assertEqual(path.read_bytes(), b"existing file")
            self.assertEqual(list(Path(directory).glob(".preserved-*.mp4")), [])


if __name__ == "__main__":
    unittest.main()
