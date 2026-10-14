"""Unicode-safe image composition and streaming H.264 output for DreamModel.

The compositor visualizes agent state; it neither generates assets nor simulates
background cells. Its small ghost history is a visual accompaniment to the
simulation's shared, persistent trace field.
"""

from __future__ import annotations
from team4.DreamModel.runtime.media import VideoWriter, find_ffmpeg, subprocess_options

from collections import OrderedDict, deque
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageEnhance, ImageOps






def load_background(path: Path | str, width: int, height: int) -> np.ndarray:
    """Load the supplied plate without inventing or regenerating its content."""
    with Image.open(Path(path)) as image:
        plate = ImageOps.fit(image.convert("RGB"), (width, height), Image.Resampling.LANCZOS)
        return np.asarray(plate, dtype=np.uint8).copy()


def load_sprite(path: Path | str, max_side: int = 512) -> np.ndarray:
    """Preserve an upstream transparent sprite and its Korean filename."""
    if max_side < 1:
        raise ValueError("max_side must be positive")
    with Image.open(Path(path)) as image:
        sprite = image.convert("RGBA")
        sprite.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return np.asarray(sprite, dtype=np.uint8).copy()


@dataclass(frozen=True)
class _Pose:
    x: float
    y: float
    scale: float
    rotation: float
    opacity: float

    @classmethod
    def from_agent(cls, agent: Any) -> "_Pose":
        return cls(float(agent.position[0]), float(agent.position[1]),
                   float(agent.scale), float(agent.rotation), float(agent.opacity))


class FrameRenderer:
    """Compose moving translucent object memories over the original plate.

    A fresh renderer fed the same frame sequence produces identical RGB pixels.
    Trace brightness uses a fixed bounded compression, never per-frame auto gain.
    Agent lists and sprite lists must have the same upstream object order.
    """

    def __init__(self, width: int, height: int, fps: int = 30, *,
                 trace_alpha_max: int = 20, ghost_gains: Sequence[float] = (.045, .075),
                 sprite_height: float = .44) -> None:
        if width < 2 or height < 2 or fps < 1:
            raise ValueError("Frame dimensions and fps must be positive")
        self.width, self.height, self.fps = width, height, fps
        if not 0 <= trace_alpha_max <= 32 or not .1 <= sprite_height <= .6:
            raise ValueError("Trace opacity or sprite size exceeds the identity-preserving range")
        if len(ghost_gains) != 2 or any(not 0 <= gain <= .15 for gain in ghost_gains):
            raise ValueError("Two bounded ghost opacity gains are required")
        self.trace_alpha_max, self.ghost_gains, self.sprite_height = trace_alpha_max, ghost_gains, sprite_height
        self._prepared: dict[int, tuple[np.ndarray, Image.Image]] = {}
        # Reuse transformed historical poses when drawing ghosts. Keep this
        # bounded: even a 300-second render must not accumulate every frame.
        self._transformed: OrderedDict[tuple[int, int, float], Image.Image] = OrderedDict()
        self._history: dict[int, deque[_Pose]] = {}
        self._history_sources: dict[int, Image.Image] = {}
        self._inactive_age: dict[int, int] = {}
        self._last_visibility: dict[int, float] = {}
        self._history_length = max(4, round(0.60 * fps))
        self._trace_ink = Image.new("RGB", (width, height), (104, 145, 174))

    def _sprite(self, array: np.ndarray) -> Image.Image:
        key = id(array)
        cached = self._prepared.get(key)
        if cached is not None and cached[0] is array:
            return cached[1]
        if array.ndim != 3 or array.shape[2] != 4 or array.dtype != np.uint8:
            raise ValueError("Sprites must be uint8 RGBA arrays")
        # Preserve source RGB and alpha exactly. Movement/opacity are agent
        # states; they must not replace the source with a grey approximation.
        result = Image.fromarray(array)
        self._prepared[key] = (array, result)
        return result

    def _transform(self, sprite: Image.Image, pose: _Pose, gain: float) -> Image.Image:
        side = max(4, round(min(self.height * self.sprite_height, self.width * 0.29) * max(0.05, pose.scale)))
        cache_key = (id(sprite), side, pose.rotation)
        cached = self._transformed.get(cache_key)
        if cached is None:
            ratio = side / max(sprite.size)
            size = (max(1, round(sprite.width * ratio)), max(1, round(sprite.height * ratio)))
            cached = sprite.resize(size, Image.Resampling.BILINEAR)
            cached = cached.rotate(pose.rotation, Image.Resampling.BILINEAR, expand=True)
            # Resampling is sufficient; blur must not erase page/hand details.
            self._transformed[cache_key] = cached
            if len(self._transformed) > 128:
                self._transformed.popitem(last=False)
        else:
            self._transformed.move_to_end(cache_key)
        transformed = cached.copy()
        alpha_gain = float(np.clip(pose.opacity * gain, 0, 1))
        transformed.putalpha(transformed.getchannel("A").point(
            [round(value * alpha_gain) for value in range(256)]))
        return transformed

    @staticmethod
    def _paste(canvas: Image.Image, sprite: Image.Image, center: tuple[float, float]) -> None:
        origin = (round(center[0] - sprite.width / 2), round(center[1] - sprite.height / 2))
        canvas.paste(sprite, origin, sprite.getchannel("A"))

    def _fragment(self, canvas: Image.Image, sprite: Image.Image, pose: _Pose,
                  progress: float, seed: int) -> None:
        """Disperse intact impressions; the original silhouette stays whole."""
        for index in range(3):
            variation = ((seed + 1) * 73856093 + index * 19349663) % 997 / 997
            angle = index * 2 * np.pi / 3 + variation + pose.rotation * np.pi / 180
            radius = self.height * .055 * progress * (.6 + .4 * variation)
            impression = sprite.copy()
            impression.putalpha(impression.getchannel("A").point(
                [round(a * .35 * progress) for a in range(256)]))
            self._paste(canvas, impression, (pose.x * self.width + np.cos(angle) * radius,
                                             pose.y * self.height + np.sin(angle) * radius))
        self._paste(canvas, sprite, (pose.x * self.width, pose.y * self.height))

    def _reveal_mask(self, trace: np.ndarray, agents: Sequence[Any], mode: str,
                     progress: float) -> Image.Image:
        """Trace and live positions decide where the next memory becomes visible."""
        if progress <= 0:
            return Image.new("L", (self.width, self.height), 0)
        if progress >= 1:
            return Image.new("L", (self.width, self.height), 255)
        rows, columns = np.indices(trace.shape, dtype=np.float32)
        x, y = columns / max(1, trace.shape[1] - 1), rows / max(1, trace.shape[0] - 1)
        proximity = np.zeros_like(trace)
        for agent in agents:
            distance = (x - float(agent.position[0])) ** 2 + (y - float(agent.position[1])) ** 2
            proximity = np.maximum(proximity, np.exp(-distance / 0.055))
        memory = trace / (1 + trace)
        if mode == "FRAGMENTATION":
            pattern = 0.40 * memory + 0.60 * proximity
        elif mode == "ACCUMULATION":
            pattern = 0.75 * memory + 0.25 * proximity
        elif mode == "EMERGENCE":
            pattern = 0.45 * (1 - memory) + 0.55 * proximity
        else:
            pattern = 0.7 * memory + 0.3 * proximity
        # The envelope is exactly 0 / 1 at the window boundaries while each
        # intermediate reveal is shaped by the actual memory and agent state.
        field = np.clip(progress + 1.6 * progress * (1 - progress) * (pattern - .5), 0, 1)
        return Image.fromarray(np.uint8(field * 255)).resize(
            (self.width, self.height), Image.Resampling.BILINEAR)

    def render(self, background: np.ndarray, sprites: Sequence[np.ndarray], agents: Sequence[Any],
               trace: np.ndarray, *, transition: Any = None,
               next_background: np.ndarray | None = None,
               next_sprites: Sequence[np.ndarray] = (), next_agents: Sequence[Any] = ()) -> np.ndarray:
        if background.shape != (self.height, self.width, 3) or background.dtype != np.uint8:
            raise ValueError("Background must match renderer dimensions as uint8 RGB")
        if len(sprites) != len(agents):
            raise ValueError("Every object agent must have exactly one sprite")
        if len(next_sprites) != len(next_agents):
            raise ValueError("Every upcoming object agent must have exactly one sprite")
        trace = np.asarray(trace, dtype=np.float32)
        if trace.ndim != 2 or not np.isfinite(trace).all() or np.any(trace < 0):
            raise ValueError("Trace must be a finite, nonnegative 2D field")
        canvas = Image.fromarray(background)
        progress, mode = 0.0, ""
        if transition is not None:
            progress = float(np.clip(transition.progress, 0, 1))
            mode = getattr(transition.mode, "value", transition.mode)
        if next_background is not None and transition is not None:
            if next_background.shape != background.shape or next_background.dtype != np.uint8:
                raise ValueError("Next background must have the same RGB dimensions")
            mask = self._reveal_mask(trace, agents, mode, progress)
            canvas = Image.composite(Image.fromarray(next_background), canvas, mask)

        memory = trace / (.25 + trace)
        trace_mask = Image.fromarray(np.uint8(memory * self.trace_alpha_max)).resize(
            (self.width, self.height), Image.Resampling.BILINEAR)
        canvas = Image.composite(self._trace_ink, canvas, trace_mask)
        all_pairs = [(sprite, agent, False) for sprite, agent in zip(sprites, agents)]
        if transition is not None:
            all_pairs += [(sprite, agent, True) for sprite, agent in zip(next_sprites, next_agents)]
        active_ids = {id(agent) for _, agent, _ in all_pairs}
        for key in list(self._history):
            if key in active_ids:
                self._inactive_age[key] = 0
                continue
            age = self._inactive_age.get(key, 0) + 1
            self._inactive_age[key] = age
            if age >= self._history_length:
                del self._history[key], self._history_sources[key], self._inactive_age[key], self._last_visibility[key]
                continue
            # A scene boundary does not abruptly erase the last silhouettes.
            old_pose = self._history[key][-1]
            ghost = self._transform(self._history_sources[key], old_pose,
                                    .12 * self._last_visibility[key] * (1 - age / self._history_length))
            self._paste(canvas, ghost, (old_pose.x * self.width, old_pose.y * self.height))
        for array, agent, upcoming in all_pairs:
            source, pose = self._sprite(array), _Pose.from_agent(agent)
            reveal = progress * progress * (3 - 2 * progress)
            visibility = 1.0
            if upcoming:
                visibility = reveal
                if mode == "ACCUMULATION":
                    incoming_progress = min(1.0, progress * 1.2)
                    visibility = incoming_progress ** 2 * (3 - 2 * incoming_progress)
            elif transition is not None and next_background is not None:
                # Both the outgoing body and its older ghost poses must finish
                # fading inside the window, not drop abruptly at the boundary.
                visibility = 1 - reveal
                if mode == "ACCUMULATION":
                    outgoing_progress = progress ** 2.2
                    visibility = 1 - outgoing_progress ** 2 * (3 - 2 * outgoing_progress)
            history = self._history.setdefault(id(agent), deque(maxlen=self._history_length))
            self._history_sources[id(agent)] = source
            self._inactive_age[id(agent)] = 0
            self._last_visibility[id(agent)] = visibility
            for fraction, gain in zip((.75, .35), self.ghost_gains):
                age = max(1, round(self._history_length * fraction))
                if len(history) >= age:
                    old_pose = history[-age]
                    ghost = self._transform(source, old_pose, gain * visibility)
                    self._paste(canvas, ghost, (old_pose.x * self.width, old_pose.y * self.height))
            if pose.opacity * visibility > 0.001:
                current = self._transform(source, pose, visibility)
                if mode == "FRAGMENTATION" and progress > 0 and not upcoming:
                    self._fragment(canvas, current, pose, progress, int(getattr(agent, "seed", 0)))
                else:
                    self._paste(canvas, current, (pose.x * self.width, pose.y * self.height))
            history.append(pose)

        if mode == "DISSOLUTION" and next_background is None:
            # Fade the entire last memory, including residual ghosts, to black.
            smooth = progress * progress * (3 - 2 * progress)
            canvas = ImageEnhance.Brightness(canvas).enhance(1 - smooth)
        return np.asarray(canvas, dtype=np.uint8).copy()
