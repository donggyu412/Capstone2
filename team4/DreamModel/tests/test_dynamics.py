"""Behavioral checks for object interaction, persistent memory, and routing."""

import unittest

import numpy as np

from team4.DreamModel.archive.adaptive_exploration import AdaptiveExploration
from team4.DreamModel.archive.object_dynamics import ObjectDynamics
from team4.DreamModel.archive.trace_memory import TraceMemory
from team4.DreamModel.archive.transition_controller import (
    TransitionController, TransitionMode, TransitionState, mode_for_stage,
)


class TraceTests(unittest.TestCase):
    def test_exact_decay_plus_deposit(self):
        memory = TraceMemory(32, 18, decay=0.8)
        positions, energy = np.array([[0.4, 0.5]]), np.array([0.7])
        memory.update(positions, energy)
        deposit = memory.field.copy()
        memory.update(positions, energy)
        np.testing.assert_allclose(memory.field, 0.8 * deposit + deposit, rtol=1e-6)
        memory.update(np.empty((0, 2)), np.empty(0))
        np.testing.assert_allclose(memory.field, 0.8 * (0.8 * deposit + deposit), rtol=1e-6)

    def test_scene_carryover_keeps_spatial_memory(self):
        memory = TraceMemory()
        memory.update(np.array([[0.4, 0.6]]), np.ones(1))
        previous = memory.field.copy()
        memory.retain()
        np.testing.assert_allclose(memory.field, previous * 0.35)
        self.assertGreater(float(memory.field.sum()), 0)

    def test_gradient_points_to_another_agents_deposit(self):
        memory = TraceMemory()
        memory.update(np.array([[0.50, 0.5]]), np.ones(1))
        gradient = memory.gradient(np.array([[0.48, 0.5], [0.52, 0.5]]))
        self.assertGreater(gradient[0, 0], 0)
        self.assertLess(gradient[1, 0], 0)


class DynamicsTests(unittest.TestCase):
    @staticmethod
    def run_dynamics(seed, frames=120):
        dynamics = ObjectDynamics(["오브제1", "오브제2", "오브제3"], seed=seed)
        memory = TraceMemory(48, 27)
        exploration = AdaptiveExploration()
        trajectory = []
        for _ in range(frames):
            activity = dynamics.step(memory, exploration.strength)
            exploration.update(activity)
            trajectory.append(dynamics.positions.copy())
        return dynamics, memory, np.array(trajectory)

    def test_same_seed_repeats_states_and_traces(self):
        a, memory_a, trajectory_a = self.run_dynamics(101)
        b, memory_b, trajectory_b = self.run_dynamics(101)
        np.testing.assert_array_equal(trajectory_a, trajectory_b)
        np.testing.assert_array_equal(memory_a.field, memory_b.field)
        self.assertEqual([o.rotation for o in a.agents], [o.rotation for o in b.agents])
        self.assertEqual([o.opacity for o in a.agents], [o.opacity for o in b.agents])

    def test_different_seeds_change_trajectories_rotation_and_trace(self):
        a, memory_a, trajectory_a = self.run_dynamics(101)
        b, memory_b, trajectory_b = self.run_dynamics(202)
        self.assertFalse(np.allclose(trajectory_a, trajectory_b))
        self.assertFalse(np.allclose(memory_a.field, memory_b.field))
        self.assertNotEqual(a.agents[0].rotation, b.agents[0].rotation)

    def test_trace_left_by_a_changes_bs_motion(self):
        memory, empty = TraceMemory(), TraceMemory()
        a = ObjectDynamics(["A"], seed=1)
        a.agents[0].position[:] = (0.5, 0.5)
        a.agents[0].velocity[:] = 0
        a.step(memory, 0)
        b_with, b_without = ObjectDynamics(["B"], seed=2), ObjectDynamics(["B"], seed=2)
        for b in (b_with, b_without):
            b.agents[0].position[:] = (0.48, 0.5)
            b.agents[0].velocity[:] = 0
        b_with.step(memory, 0)
        b_without.step(empty, 0)
        self.assertGreater(b_with.agents[0].velocity[0], b_without.agents[0].velocity[0])
        self.assertGreater(b_with.agents[0].position[0], b_without.agents[0].position[0])

    def test_no_trace_update_option_keeps_shared_frame_synchronous(self):
        memory = TraceMemory()
        memory.update(np.array([[0.4, 0.4]]), np.ones(1))
        before = memory.field.copy()
        group_a, group_b = ObjectDynamics(["A"]), ObjectDynamics(["B"])
        group_a.step(memory, 0.0002, update_trace=False)
        group_b.step(memory, 0.0002, update_trace=False)
        np.testing.assert_array_equal(memory.field, before)
        combined = np.concatenate((group_a.positions, group_b.positions))
        memory.update(combined, np.concatenate((group_a.energies, group_b.energies)))
        self.assertFalse(np.array_equal(memory.field, before))

    def test_state_is_alive_and_bounded_for_a_full_75_second_scene(self):
        dynamics, memory, trajectory = self.run_dynamics(303, frames=2250)
        self.assertTrue(np.isfinite(trajectory).all())
        self.assertTrue(np.logical_and(trajectory >= 0.10, trajectory <= 0.90).all())
        self.assertGreater(float(np.max(np.ptp(trajectory, axis=0))), 0.1)
        for agent in dynamics.agents:
            self.assertGreater(agent.opacity, 0.35)
            self.assertTrue(0.7 < agent.scale < 1.2)
            self.assertLessEqual(np.linalg.norm(agent.velocity), dynamics.max_speed + 1e-10)
        self.assertTrue(np.isfinite(memory.field).all())

    def test_image_guidance_is_local_and_optional(self):
        left_to_right = np.tile(np.linspace(0, 1, 16), (16, 1))
        guided = ObjectDynamics(["A"], guidance=left_to_right)
        neutral = ObjectDynamics(["A"])
        for dynamics in (guided, neutral):
            dynamics.agents[0].velocity[:] = 0
        guided.step(TraceMemory(), 0)
        neutral.step(TraceMemory(), 0)
        self.assertGreater(guided.agents[0].velocity[0], neutral.agents[0].velocity[0])
        self.assertLess(guided.agents[0].velocity[0], 0.00012)

    def test_dissolution_actually_slows_and_fades_existing_agents(self):
        normal, fading = ObjectDynamics(["A"]), ObjectDynamics(["A"])
        for dynamics in (normal, fading):
            dynamics.agents[0].velocity[:] = (0.001, 0.0)
            dynamics.agents[0].opacity = 0.7
            dynamics.frame = 300
        normal.step(TraceMemory(), 0)
        fading.step(TraceMemory(), 0, TransitionState(TransitionMode.DISSOLUTION, 1))
        self.assertLess(np.linalg.norm(fading.agents[0].velocity), np.linalg.norm(normal.agents[0].velocity))
        self.assertLess(fading.agents[0].opacity, normal.agents[0].opacity)


class AdaptiveTests(unittest.TestCase):
    def test_stagnation_increases_and_excess_activity_decreases_exploration(self):
        low, high = AdaptiveExploration(), AdaptiveExploration()
        for _ in range(100):
            low.update(0)
            high.update(1)
        self.assertGreater(low.strength, 0.00025)
        self.assertLess(high.strength, 0.00025)
        for _ in range(1000):
            low.update(0, 1)
            high.update(1, 0)
        self.assertEqual(low.strength, low.max_strength)
        self.assertEqual(high.strength, high.min_strength)

    def test_audio_changes_strength_without_changing_emotion(self):
        silent, sound = AdaptiveExploration(), AdaptiveExploration()
        for _ in range(20):
            silent.update(0.32, 0)
            sound.update(0.32, 1)
        self.assertGreater(sound.strength, silent.strength)
        self.assertTrue(0 < sound.smoothed_audio < 1)

    def test_feedback_is_the_documented_formula(self):
        control = AdaptiveExploration(smoothing=0.5)
        initial = control.strength
        result = control.update(0.2, 0.8)
        expected = initial + control.learning_rate * (0.32 - 0.26) + control.audio_gain * 0.4
        self.assertAlmostEqual(result, expected)


class TransitionTests(unittest.TestCase):
    def test_frame_windows_have_exact_start_and_end(self):
        smoke = TransitionController(window_seconds=1)
        self.assertIsNone(smoke.state_for_frame("기", 89, 120, 30))
        self.assertEqual(smoke.state_for_frame("기", 90, 120, 30).progress, 0)
        self.assertEqual(smoke.state_for_frame("기", 119, 120, 30).progress, 1)
        final = TransitionController(window_seconds=6)
        self.assertIsNone(final.state_for_frame("결", 2069, 2250, 30))
        self.assertEqual(final.state_for_frame("결", 2070, 2250, 30).progress, 0)
        self.assertEqual(final.state_for_frame("결", 2249, 2250, 30).progress, 1)

    def test_single_frame_window_and_invalid_frame_arguments(self):
        control = TransitionController(window_seconds=1 / 30)
        self.assertIsNone(control.state_for_frame("전", 118, 120, 30))
        self.assertEqual(control.state_for_frame("전", 119, 120, 30).progress, 1)
        for frame, total, fps in ((-1, 120, 30), (120, 120, 30), (0.5, 120, 30),
                                  (0, 0, 30), (0, 120, 0), (0, 120, 30.0), (False, 120, 30)):
            with self.subTest(frame=frame, total=total, fps=fps), self.assertRaises(ValueError):
                control.state_for_frame("기", frame, total, fps)

    def test_only_literal_upstream_labels_route(self):
        self.assertEqual([mode_for_stage(stage) for stage in ("기", "승", "전", "결")], list(TransitionMode))
        for invalid in (1, "1", "scene_01", "기 ", "", None):
            with self.subTest(stage=invalid), self.assertRaises(ValueError):
                mode_for_stage(invalid)

    def test_transition_is_only_active_in_configured_final_window(self):
        control = TransitionController(window_seconds=5)
        self.assertIsNone(control.state("전", 69.999, 75))
        self.assertEqual(control.state("전", 70, 75).progress, 0)
        self.assertEqual(control.state("전", 72.5, 75).progress, 0.5)
        self.assertEqual(control.state("전", 75, 75).progress, 1)
        with self.assertRaises(ValueError):
            control.state("scene_01", 0, 75)


if __name__ == "__main__":
    unittest.main()
