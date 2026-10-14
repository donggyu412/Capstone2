"""Continuous scene samples, causal trace memory, and bounded adaptive control.

No cell activation/growth rules and no per-object floating PNG agents.
Raster fields only gather deposits/interactions of continuously moving samples.
"""
from __future__ import annotations

from dataclasses import dataclass
import cv2
import numpy as np
from .scene_composition import SceneComposition
from .trace_memory import sample_field
from .transition_controller import TransitionMode, TransitionState


def smooth(value):
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)


def splat(positions, values, width, height, sigma=1.0):
    """Bilinear particle deposition; convolution is a footprint, not diffusion."""
    xy = np.clip(positions, 0, 1) * (width - 1, height - 1)
    lo = xy.astype(np.int32)
    frac = xy - lo
    values = np.asarray(values, dtype=np.float32)
    if values.ndim == 1:
        values = values[:, None]
    channels = values.shape[1]
    result = np.zeros((height * width, channels), np.float32)
    for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        x = np.minimum(lo[:, 0] + ox, width - 1)
        y = np.minimum(lo[:, 1] + oy, height - 1)
        weight = (frac[:, 0] if ox else 1-frac[:, 0]) * (frac[:, 1] if oy else 1-frac[:, 1])
        for channel in range(channels):
            result[:, channel] += np.bincount(y * width + x, weights=weight * values[:, channel], minlength=width*height)
    result = result.reshape(height, width, channels)
    if sigma:
        result = cv2.GaussianBlur(result, (0, 0), sigma)
        if result.ndim == 2:
            result = result[:, :, None]
    return result


class FormationMemory:
    def __init__(self, width=128, height=72):
        self.width, self.height = width, height
        self.field = np.zeros((height, width), np.float32)
        self.color = np.zeros((height, width, 3), np.float32)

    def gradient(self, positions):
        gy, gx = np.gradient(self.field)
        return sample_field(np.stack((gx, gy), axis=-1), positions)

    def update(self, positions, colors, energy, decay):
        deposited = splat(positions, np.column_stack((energy, colors * energy[:, None])),
                          self.width, self.height, .85)
        self.field *= decay
        self.color *= decay
        self.field += deposited[:, :, 0] * .045
        self.color += deposited[:, :, 1:] * .045

    def retain(self, fraction):
        self.field *= fraction
        self.color *= fraction


@dataclass
class AdaptiveBalance:
    convergence: float = .8
    exploration: float = .15
    readability: float = 0.0

    def update(self, coherence: float, coverage: float, intensity: float, rms: float, onset: float):
        # Readability is a geometric proxy, NOT a semantic recognition score.
        observed = .65 * np.clip(coherence, 0, 1) + .35 * np.clip(coverage, 0, 1)
        self.readability += .10 * (observed - self.readability)
        desired = float(smooth((self.readability - .38) / .42))
        self.convergence += .08 * ((.96 - .58 * desired) - self.convergence)
        self.exploration += .08 * ((.055 + .30 * desired + .04 * intensity + .065 * rms + .08 * onset) - self.exploration)
        self.convergence = float(np.clip(self.convergence, .30, .98))
        self.exploration = float(np.clip(self.exploration, .04, .55))


class ParticleFormation:
    def __init__(self, composition: SceneComposition, seed: int, scene_id: int,
                 count=6500, width=128, height=72, balance=None):
        self.composition = composition
        self.rng = np.random.default_rng(np.random.SeedSequence([seed, scene_id]))
        self.width, self.height = width, height
        self.balance = balance if balance is not None else AdaptiveBalance()
        h, w = composition.rgb.shape[:2]
        probability = composition.saliency.ravel().astype(np.float64)
        probability /= probability.sum()
        indices = self.rng.choice(w*h, count, p=probability)
        self.home = np.column_stack(((indices % w + self.rng.random(count)) / w,
                                     (indices // w + self.rng.random(count)) / h))
        self.colors = composition.rgb.reshape(-1, 3)[indices]
        self.birth = composition.reveal.ravel()[indices] + self.rng.uniform(0, .07, count)
        self.labels = composition.labels.ravel()[indices]
        # Fragments originate near several incomplete memory sites, not as a full image.
        center = np.array([.50, .52])
        self.position = np.clip(center + (self.home-center) * .45 + self.rng.normal(0, .09, (count, 2)), .01, .99)
        self.velocity = self.rng.normal(0, .001, (count, 2))
        self.noise = self.rng.normal(0, 1, (count, 2))
        self.phase = self.rng.uniform(0, 2*np.pi, count)
        self.active = np.zeros(count)
        self.coverage = np.zeros((height, width), np.float32)
        self.flow = np.zeros((height, width, 2), np.float32)
        self.trace_force_mean = 0.0
        self.coherence = 0.0
        self.last_rms = self.last_onset = 0.0
        self.last_transition = None
        self.trace_influence = .00042
        self.drift_field = self.rng.normal(0, 1, (9, 16, 2)).astype(np.float32)
        self.drift_field = cv2.GaussianBlur(self.drift_field, (0, 0), 1.1)
        self.drift_field /= max(float(np.std(self.drift_field)), .01)
        self.initial_home = self.home.copy()

    def step(self, memory: FormationMemory, fraction: float, seconds: float,
             rms: float, onset: float, transition: TransitionState | None = None):
        self.last_rms, self.last_onset, self.last_transition = rms, onset, transition
        intensity = self.composition.plan.emotion_intensity
        profile = self.composition.plan.emotion_parameters
        # Sound modulates birth rate, not emotion inference.
        self.active = smooth((fraction - self.birth) / (.16 - .025*rms))
        delta = self.home - self.position
        errors = np.linalg.norm(delta, axis=1)
        total = max(float(self.active.sum()), 1.)
        self.coherence = float(np.sum(np.exp(-errors/.055) * self.active) / total)
        footprint = splat(self.position, self.active, self.width, self.height, 1.15)[:, :, 0]
        occupied = float(np.mean(1 - np.exp(-footprint * 6)))
        self.balance.update(self.coherence, occupied, intensity, rms, onset)
        memory_force = memory.gradient(self.position)
        memory_force = np.tanh(memory_force * 5)
        self.trace_force_mean = float(np.mean(np.linalg.norm(memory_force * self.trace_influence, axis=1)))
        # Local mean velocity: continuous particles share a transient spatial index.
        moment = splat(self.position, np.column_stack((self.active, self.velocity*self.active[:, None])),
                       self.width, self.height, 1.3)
        mean_velocity = moment[:, :, 1:] / np.maximum(moment[:, :, :1], 1e-6)
        alignment = sample_field(mean_velocity, self.position) - self.velocity
        self.noise = .92*self.noise + .39*self.rng.normal(0, 1, self.noise.shape)
        drift = sample_field(self.drift_field, self.position)
        drift *= np.sin(seconds * .85 + self.phase[:, None] * .05)
        p = transition.smooth_progress if transition else 0.
        destabilize = p if transition and transition.mode == TransitionMode.FRAGMENTATION else 0.
        decay_out = p if transition and transition.mode == TransitionMode.DISSOLUTION else 0.
        # This guidance is a structural prior; nonzero exploration persists after formation.
        guidance = delta * (.014*self.balance.convergence) * (1 - .88*destabilize)
        force = guidance + self.trace_influence*memory_force + .065*alignment
        force += self.balance.exploration * profile["noise_gain"] * (.00034*self.noise + .00030*drift)
        force += destabilize * (.0009*drift + .00035*self.noise) * (1 + .3*onset)
        force += decay_out * .0003 * drift
        inertia = float(np.clip(profile["inertia"] - .13, .75, .88))
        self.velocity = inertia*self.velocity + force
        speed = np.linalg.norm(self.velocity, axis=1)
        self.velocity *= np.minimum(1, .007 / np.maximum(speed, 1e-9))[:, None]
        self.position += self.velocity * self.active[:, None]
        escaped = (self.position < .005) | (self.position > .995)
        self.velocity[escaped] *= -.5
        self.position = np.clip(self.position, .005, .995)
        # Selection/renewal of a small subset prevents a frozen exact reconstruction.
        renewal = self.rng.random(len(self.home)) < .0009*self.balance.exploration
        self.velocity[renewal] += self.rng.normal(0, .0018, (int(renewal.sum()), 2))
        self.coverage *= .975 - .018*destabilize
        self.coverage += footprint * (.065 + .012*rms)
        # Gather displacement at source sites to deform the whole composed scene coherently.
        source_moment = splat(self.home, np.column_stack((self.active, (self.position-self.home)*self.active[:, None])),
                              self.width, self.height, 2.2)
        self.flow = source_moment[:, :, 1:] / np.maximum(source_moment[:, :, :1], 1e-6)
        return self.active * (1 - .85*decay_out)

    def snapshot(self):
        return {
            "readability_proxy": self.balance.readability,
            "coherence": self.coherence,
            "coverage_mean": float(np.mean(1 - np.exp(-self.coverage))),
            "convergence": self.balance.convergence, "exploration": self.balance.exploration,
            "trace_force_mean": self.trace_force_mean,
            "rms": self.last_rms, "onset": self.last_onset,
            "active_samples": float(self.active.sum()),
            "position_sample": self.position[::max(1,len(self.position)//16)].tolist(),
        }


class FormationRenderer:
    """One common spatial field reveals/deforms background and objects together."""
    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.yy, self.xx = np.mgrid[:height, :width].astype(np.float32)

    def render(self, group: ParticleFormation, memory: FormationMemory, fraction: float,
               transition: TransitionState | None = None):
        rgb = group.composition.rgb
        flow = cv2.resize(group.flow.astype(np.float32), (self.width,self.height), interpolation=cv2.INTER_CUBIC)
        # Bounded shared warp: recognizable source structures survive local motion.
        mapx = self.xx - np.clip(flow[:,:,0], -.07, .07) * self.width
        mapy = self.yy - np.clip(flow[:,:,1], -.07, .07) * self.height
        formed = cv2.remap(rgb, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        cover = cv2.resize(cv2.GaussianBlur(group.coverage,(0,0),1.0), (self.width,self.height), interpolation=cv2.INTER_LINEAR)
        reveal = 1 - np.exp(-np.maximum(cover,0) * 2.3)
        availability = smooth((fraction - group.composition.reveal) / .16)
        availability = cv2.remap(availability, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        visibility = reveal * availability
        # Early color/line traces are actual moving samples, not full-screen decorative noise.
        dots = splat(group.position, np.column_stack((group.active, group.colors*group.active[:,None])),
                     group.width, group.height, .55)
        color_dots = dots[:,:,1:] / np.maximum(dots[:,:,:1], 1e-6)
        strength = (1 - np.exp(-dots[:,:,:1]*1.8))
        particles = cv2.resize(color_dots*strength, (self.width,self.height), interpolation=cv2.INTER_LINEAR)
        coherence = float(smooth((group.balance.readability-.35)/.45))
        result = formed * visibility[:,:,None] * (.80 + .17*coherence)
        result += particles * (.24 - .21*coherence) * (1-visibility[:,:,None]*.75)
        trace_rgb = memory.color / np.maximum(memory.field[:,:,None], 1e-6)
        trace_visible = (1-np.exp(-memory.field[:,:,None]*2))
        trace_image = cv2.resize(trace_rgb*trace_visible,(self.width,self.height),interpolation=cv2.INTER_LINEAR)
        result += trace_image * .075 * (1-visibility[:,:,None]*.7)
        if transition:
            p = transition.smooth_progress
            if transition.mode == TransitionMode.ACCUMULATION:
                result *= 1 - p**2.2
            elif transition.mode == TransitionMode.FRAGMENTATION:
                # Holes follow real sparse deposits; no triangular replacement assets.
                holes = cv2.resize(dots[:,:,0],(self.width,self.height))
                breakup = np.clip(holes*3, 0, 1)
                result *= (1-p*.70*(1-breakup))[:,:,None]
                result *= 1 - p*p
            elif transition.mode == TransitionMode.DISSOLUTION:
                result *= (1-p)**1.6
            else:
                result *= 1 - p
        return np.clip(result, 0, 1).astype(np.float32)
