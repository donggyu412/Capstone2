"""Meaning must affect real states while source pixels and labels survive."""

from dataclasses import replace
import unittest

import numpy as np

from team4.DreamModel.config import REPO_ROOT
from team4.DreamModel.frame_renderer import FrameRenderer
from team4.DreamModel.input_loader import load_inputs
from team4.DreamModel.main import parse_config
from team4.DreamModel.object_dynamics import ObjectDynamics
from team4.DreamModel.semantic_conditioning import SemanticLibrary, SceneConditioning
from team4.DreamModel.trace_memory import TraceMemory


class SemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenes = load_inputs(REPO_ROOT / "team4/input").scenes
        cls.library = SemanticLibrary()

    def simulate(self, scene, seed=101, frames=120, trace_influence=None):
        plan = self.library.plan(scene)
        conditioning = SceneConditioning(plan, self.library, 5, 1)
        settings = self.library.settings["motion"]
        dynamics = ObjectDynamics([obj.object_id for obj in scene.objects], seed=seed,
                                  conditioning=conditioning,
                                  trace_influence=settings["trace_influence"] if trace_influence is None else trace_influence,
                                  guidance_influence=settings["guidance_influence"])
        memory = TraceMemory(decay=.98, **self.library.settings["trace"])
        paths = []
        for frame in range(frames):
            dynamics.step(memory, .0001, scene_seconds=frame / 30)
            paths.append(dynamics.positions.copy())
        return dynamics, memory, np.asarray(paths)

    def test_only_observed_emotion_has_a_profile(self):
        labels = {scene.emotion_label for scene in self.scenes}
        self.assertEqual(set(self.library.settings["emotion_profiles"]), labels)
        with self.assertRaisesRegex(ValueError, "No artistic mapping"):
            self.library.plan(replace(self.scenes[0], emotion_label="unknown"))

    def test_contact_and_separation_are_not_read_as_a_falling_hand(self):
        hand = self.library.plan(self.scenes[3]).objects[2]
        figure = self.library.plan(self.scenes[2]).objects[2]
        self.assertNotIn("falling", hand.cues)
        self.assertNotIn("falling", figure.cues)
        first = self.library.plan(self.scenes[0])
        self.assertEqual(next(obj.role for obj in first.objects if obj.reveal_rank == 0), "journal")

    def test_trace_sensing_reaches_another_objects_path_without_spreading_it(self):
        trace = TraceMemory()
        trace.update(np.array([[.50, .5]]), np.array([1.]))
        before = trace.field.copy()
        local = trace.gradient(np.array([[.40, .5]]))
        footprint = trace.gradient(np.array([[.40, .5]]), sensing_radius=.10)
        self.assertAlmostEqual(float(local[0, 0]), 0)
        self.assertGreater(float(footprint[0, 0]), 0)
        np.testing.assert_array_equal(trace.field, before)

    def test_plan_evidence_is_from_input_and_stage_does_not_score_it(self):
        for scene in self.scenes:
            plan = self.library.plan(scene)
            self.assertEqual(plan.emotion_label, scene.emotion_label)
            self.assertEqual(plan.emotion_intensity, scene.emotion_intensity)
            self.assertEqual([obj.name for obj in plan.objects], [obj.name for obj in scene.objects])
            self.assertIn(plan.composition_evidence, scene.title + scene.story)
            for obj in plan.objects:
                for evidence in obj.evidence:
                    self.assertIn(evidence, scene.story)
            for relation in plan.relations:
                self.assertIn(relation.evidence, scene.story)
            other = self.library.plan(replace(scene, stage="결"))
            self.assertEqual(plan.as_report(), other.as_report())

    def test_title_and_story_control_reveal_and_guidance(self):
        scene = self.scenes[2]
        plan = self.library.plan(scene)
        self.assertEqual(next(obj.role for obj in plan.objects if obj.reveal_rank == 0), "floor")
        altered = replace(scene, title="서류철", story="서류철과 종이가 있다. 형상이 있다. 타일 금이 있다.")
        changed = self.library.plan(altered)
        self.assertEqual(next(obj.role for obj in changed.objects if obj.reveal_rank == 0), "record")
        self.assertFalse(changed.relations)
        _, _, original_path = self.simulate(scene)
        _, _, changed_path = self.simulate(altered)
        self.assertFalse(np.allclose(original_path, changed_path))

    def test_intensity_changes_motion_without_changing_label(self):
        strong = self.scenes[0]
        weak = replace(strong, emotion_intensity=.1)
        a, _, path_a = self.simulate(strong)
        b, _, path_b = self.simulate(weak)
        self.assertFalse(np.allclose(path_a, path_b))
        self.assertEqual(a.conditioning.plan.emotion_label, b.conditioning.plan.emotion_label)
        self.assertGreater(a.conditioning.plan.emotion_parameters["opacity_fluctuation"],
                           b.conditioning.plan.emotion_parameters["opacity_fluctuation"])

    def test_identity_pixels_are_not_desaturated_or_darkened(self):
        source = np.zeros((12, 12, 4), dtype=np.uint8)
        source[2:10, 2:10] = [220, 83, 31, 207]
        renderer = FrameRenderer(128, 72)
        np.testing.assert_array_equal(np.asarray(renderer._sprite(source)), source)

    def test_background_is_exact_without_agents_or_trace(self):
        source = np.random.default_rng(42).integers(0, 256, (72, 128, 3), dtype=np.uint8)
        result = FrameRenderer(128, 72).render(source, [], [], np.zeros((9, 16)))
        np.testing.assert_array_equal(result, source)

    def test_trace_is_local_bounded_and_affects_conditioned_motion(self):
        memory = TraceMemory(decay=.98, radius=1.25, deposit_strength=.04)
        for _ in range(20):
            memory.update(np.array([[.50, .5]]), np.array([1.]))
        plate = np.zeros((180, 320, 3), dtype=np.uint8)
        result = FrameRenderer(320, 180).render(plate, [], [], memory.field)
        self.assertLess(np.count_nonzero(result.any(axis=-1)) / (320 * 180), .05)
        self.assertLessEqual(int(result.max()), 22)
        a, _, path_a = self.simulate(self.scenes[0])
        _, _, path_b = self.simulate(self.scenes[0], trace_influence=0)
        self.assertGreater(float(np.max(np.abs(path_a - path_b))), .0001)
        self.assertTrue(any(np.linalg.norm(agent.trace_force) > 0 for agent in a.agents))

    def test_staggered_reveal_and_no_invisible_deposit(self):
        scene = self.scenes[0]
        condition = SceneConditioning(self.library.plan(scene), self.library, 5, 1)
        group = ObjectDynamics([obj.object_id for obj in scene.objects], conditioning=condition)
        group.step(TraceMemory(), .0001, scene_seconds=0)
        for agent, obj in zip(group.agents, condition.plan.objects):
            if obj.reveal_rank:
                self.assertEqual(agent.opacity, 0)
                self.assertEqual(agent.energy, 0)
        self.assertEqual([condition.beat(t) for t in (0, 1, 3, 4.5)],
                         ["Establish", "Reveal", "Interaction", "Transition"])

    def test_source_profiles_keep_six_second_final_window_and_short_preview(self):
        preview, _ = parse_config(["--preview"])
        self.assertEqual((preview.width, preview.height, preview.fps, preview.duration), (960, 540, 30, 20))
        self.assertEqual(preview.total_frames, 600)
        final, _ = parse_config(["--final"])
        self.assertEqual((final.width, final.height, final.duration, final.transition_seconds), (1920, 1080, 300, 6))

    def test_conditioned_seed_reproducibility(self):
        _, first_memory, first = self.simulate(self.scenes[0])
        _, second_memory, second = self.simulate(self.scenes[0])
        _, _, other = self.simulate(self.scenes[0], seed=202)
        np.testing.assert_array_equal(first, second)
        np.testing.assert_array_equal(first_memory.field, second_memory.field)
        self.assertFalse(np.allclose(first, other))


if __name__ == "__main__":
    unittest.main()
