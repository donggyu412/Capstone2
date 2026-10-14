"""Objects move through and contribute to shared fading spatial memories."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Sequence, TYPE_CHECKING

import numpy as np

from .trace_memory import TraceMemory, sample_field
from .transition_controller import TransitionMode, TransitionState

if TYPE_CHECKING:
    from .semantic_conditioning import SceneConditioning


@dataclass
class ObjectAgent:
    object_id: str
    position: np.ndarray
    velocity: np.ndarray
    scale: float
    rotation: float
    opacity: float
    activity: float
    energy: float
    seed: int
    rng: np.random.Generator = field(repr=False)
    phase: float = 0.0
    appearance_delay: float = 0.0
    beat: str = "Unconditioned"
    trace_force: np.ndarray = field(default_factory=lambda: np.zeros(2))
    semantic_force: np.ndarray = field(default_factory=lambda: np.zeros(2))


class ObjectDynamics:
    """Frame-state simulation with no predefined paths or fixed image targets.

    Position and velocity are normalized screen x/y coordinates. Scale is a
    multiplier on the compositor's nominal sprite size, rotation is degrees,
    and activity is speed divided by the configured maximum speed. Parameters
    describe numerical integration and do not reinterpret the narrative label.
    """

    def __init__(
        self,
        object_ids: Sequence[str],
        seed: int = 101,
        guidance: np.ndarray | None = None,
        intensity: float = 0.5,
        fps: int = 30,
        *,
        inertia: float = 0.965,
        trace_influence: float = 0.002,
        guidance_influence: float = 0.00012,
        max_speed: float = 0.004,
        conditioning: SceneConditioning | None = None,
    ) -> None:
        if fps <= 0 or max_speed <= 0:
            raise ValueError("fps and maximum speed must be positive")
        if not all(math.isfinite(v) for v in (intensity, inertia, trace_influence, guidance_influence, max_speed)):
            raise ValueError("dynamics settings must be finite")
        if not 0 <= intensity <= 1 or not 0 <= inertia < 1:
            raise ValueError("intensity must be in [0, 1]; inertia in [0, 1)")
        if trace_influence < 0 or guidance_influence < 0:
            raise ValueError("guidance coefficients cannot be negative")
        if len(set(object_ids)) != len(object_ids):
            raise ValueError("object ids must be unique within a scene")
        self.fps, self.intensity, self.inertia = fps, intensity, inertia
        self.trace_influence = trace_influence
        self.guidance_influence = guidance_influence
        self.max_speed = max_speed
        self.conditioning = conditioning
        self.frame = 0
        self._guidance_gradient = self._prepare_guidance(guidance)
        self.agents: list[ObjectAgent] = []
        for object_id in object_ids:
            digest = hashlib.blake2b(f"{seed}:{object_id}".encode("utf-8"), digest_size=8).digest()
            agent_seed = int.from_bytes(digest, "little")
            rng = np.random.default_rng(agent_seed)
            self.agents.append(ObjectAgent(
                object_id=object_id,
                position=rng.uniform((0.2, 0.2), (0.8, 0.8)),
                velocity=rng.normal(0, 0.0006, 2),
                scale=float(rng.uniform(0.82, 1.10)),
                rotation=float(rng.uniform(-16, 16)),
                opacity=0.0,
                activity=0.0,
                energy=0.25,
                seed=agent_seed,
                rng=rng,
                phase=float(rng.uniform(0, 2 * np.pi)),
                appearance_delay=float(rng.uniform(0.05, 0.65)),
            ))
        if self.conditioning is not None:
            self.conditioning.initialize(self.agents)

    @staticmethod
    def _prepare_guidance(guidance: np.ndarray | None) -> np.ndarray:
        if guidance is None:
            return np.zeros((2, 2, 2), dtype=np.float64)
        luminance = np.asarray(guidance, dtype=np.float64)
        if luminance.ndim != 2 or min(luminance.shape) < 2 or not np.isfinite(luminance).all():
            raise ValueError("guidance must be a finite two-dimensional luminance field")
        vertical, horizontal = np.gradient(np.clip(luminance, 0, 1))
        gradient = np.stack((horizontal, vertical), axis=-1)
        # A bounded, weak local image gradient. No image-coordinate target or
        # image reconstruction loss is introduced by this normalization.
        norm = float(np.max(np.linalg.norm(gradient, axis=-1)))
        return gradient / max(1.0, norm)

    @property
    def positions(self) -> np.ndarray:
        return np.asarray([agent.position for agent in self.agents], dtype=np.float64).reshape(-1, 2)

    @property
    def energies(self) -> np.ndarray:
        return np.asarray([agent.energy for agent in self.agents], dtype=np.float64)

    def step(
        self,
        trace: TraceMemory,
        exploration_strength: float,
        transition: TransitionState | None = None,
        *,
        update_trace: bool = True,
        scene_seconds: float | None = None,
    ) -> float:
        """Read H(t), update all agents, then calculate H(t+1) once.

        Normally the caller must not call trace.update again for this step.
        When updating multiple overlapping groups, use update_trace=False on
        each group, then update the memory once with all positions/energies.
        The default integration clock is 30 fps, matching the project output.
        """
        if not math.isfinite(exploration_strength) or exploration_strength < 0:
            raise ValueError("exploration strength must be finite and nonnegative")
        positions = self.positions
        radius = self.conditioning.settings["motion"]["trace_sensing_radius"] if self.conditioning else 0.0
        gradients = trace.gradient(positions, sensing_radius=radius)
        guidance = sample_field(self._guidance_gradient, positions)
        progress = transition.smooth_progress if transition is not None else 0.0
        mode = transition.mode if transition is not None else None
        dt = 30.0 / self.fps
        time_seconds = self.frame / self.fps if scene_seconds is None else scene_seconds

        for index, agent in enumerate(self.agents):
            rho = self.inertia
            alpha = self.trace_influence
            sigma = exploration_strength
            local_guidance = guidance[index]
            speed_limit = self.max_speed
            cues = None
            if self.conditioning is not None:
                cues = self.conditioning.sample(index, positions, time_seconds, agent.phase)
                rho, speed_limit = cues.inertia, cues.speed_limit
                limits = self.conditioning.settings["exploration"]
                sigma = float(np.clip(sigma * cues.noise_gain, limits["min_strength"], limits["max_strength"]))
                image_gain = self.conditioning.settings["motion"]["image_guidance_strength"]
                local_guidance = cues.guidance + image_gain * local_guidance
                local_guidance /= max(1.0, float(np.linalg.norm(local_guidance)))
                agent.beat = cues.beat
            size_factor, opacity_factor = 1.0, 1.0
            if mode == TransitionMode.EMERGENCE:
                size_factor = 1.0 + 0.15 * progress
                opacity_factor = 1.0 - 0.7 * progress
            elif mode == TransitionMode.ACCUMULATION:
                alpha *= 1.0 + progress
                size_factor = 1.0 + 0.2 * progress
                opacity_factor = 1.0 - 0.4 * progress
            elif mode == TransitionMode.FRAGMENTATION:
                sigma *= 1.0 + 1.2 * progress
                size_factor = 1.0 - 0.4 * progress
                opacity_factor = 1.0 - 0.75 * progress
            elif mode == TransitionMode.DISSOLUTION:
                rho -= 0.12 * progress
                sigma *= 1.0 - 0.85 * progress
                size_factor = 1.0 - 0.15 * progress
                opacity_factor = 1.0 - 0.95 * progress

            if cues is not None and mode != TransitionMode.DISSOLUTION:
                # The compositor fades whole identities. Do not additionally
                # destroy their silhouette or amplify motion into an explosion.
                size_factor = 1 + (0.06 if mode == TransitionMode.ACCUMULATION else -0.03) * progress
                opacity_factor = 1.0
                sigma = min(sigma, self.conditioning.settings["exploration"]["max_strength"])

            epsilon = np.clip(agent.rng.normal(0.0, 1.0, 2), -2.0, 2.0)
            # Project formula 2. At the standard 30 fps dt=1 exactly:
            # v' = rho*v + alpha*grad(H) + beta*G + sigma*epsilon; x'=x+v'.
            agent.trace_force = alpha * gradients[index]
            agent.semantic_force = self.guidance_influence * local_guidance
            force = agent.trace_force + agent.semantic_force + sigma * epsilon
            velocity = rho**dt * agent.velocity + dt * force
            speed = float(np.linalg.norm(velocity))
            if speed > speed_limit:
                velocity *= speed_limit / speed
            position = agent.position + dt * velocity
            # A reflecting viewport boundary only prevents sprites escaping;
            # it does not attract them to a fixed composition or path.
            for axis in range(2):
                if position[axis] < 0.10:
                    position[axis] = 0.10 + (0.10 - position[axis])
                    velocity[axis] = abs(velocity[axis]) * 0.65
                elif position[axis] > 0.90:
                    position[axis] = 0.90 - (position[axis] - 0.90)
                    velocity[axis] = -abs(velocity[axis]) * 0.65
            agent.position = np.clip(position, 0.10, 0.90)
            agent.velocity = velocity
            agent.activity = min(1.0, float(np.linalg.norm(velocity)) / speed_limit)
            agent.energy = 0.25 + 0.75 * agent.activity
            agent.phase += dt * (0.012 + 0.014 * agent.activity)
            desired_scale = (0.94 + 0.12 * math.sin(agent.phase)) * size_factor
            if cues is not None:
                desired_scale = cues.scale * size_factor
            agent.scale += min(1.0, 0.035 * dt) * (desired_scale - agent.scale)
            if cues is None:
                agent.rotation += dt * (
                    float(agent.rng.normal(0, 0.07)) + 0.12 * math.sin(agent.phase)
                    + 25 * float(velocity[0] - velocity[1]))
            else:
                # Keep pages/hands readable; a bounded flutter reacts to text
                # cues and emotion without replacing the source's geometry.
                desired_rotation = 4 * math.sin(agent.phase) + 10 * cues.rotation_step
                agent.rotation += .09 * dt * (desired_rotation - agent.rotation)
            agent.rotation = (agent.rotation + 180) % 360 - 180
            desired_opacity = (
                0.61 + 0.10 * self.intensity + 0.10 * math.cos(agent.phase)
            ) * opacity_factor
            if cues is not None:
                pulse = .5 + .5 * math.sin(time_seconds * 4.1 + agent.phase)
                desired_opacity = self.conditioning.settings["motion"]["base_opacity"]
                desired_opacity *= cues.visibility * (1 - cues.opacity_fluctuation * pulse) * opacity_factor
            elif time_seconds < agent.appearance_delay:
                desired_opacity = 0.0
            agent.opacity += min(1.0, (0.14 if cues else 0.045) * dt) * (desired_opacity - agent.opacity)
            if cues is not None:
                # Invisible objects cannot write a visible path before reveal.
                agent.energy *= agent.opacity

        if update_trace:
            trace.update(self.positions, self.energies)
        self.frame += 1
        return float(np.mean([agent.activity for agent in self.agents])) if self.agents else 0.0
