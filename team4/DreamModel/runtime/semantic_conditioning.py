"""Evidence-backed scene direction over a stateful motion engine.

Rules select tendencies and reveal order from supplied text. They do not write
events, infer emotion/stage, reconstruct images, or specify object trajectories.
All numerical mappings are artistic, configurable choices, not scientific laws.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from team4.DreamModel.runtime.input_loader import SceneInput


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs/semantic_config.json"


@dataclass(frozen=True)
class ObjectPlan:
    object_id: str
    name: str
    role: str
    aliases: tuple[str, ...]
    region: tuple[float, float, float, float]
    scale: float
    reveal_rank: int
    cues: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Relation:
    source: int
    target: int
    evidence: str


@dataclass(frozen=True)
class ScenePlan:
    title: str
    composition: str
    composition_evidence: str
    flow: tuple[float, float]
    emotion_label: str
    emotion_intensity: float
    emotion_parameters: dict[str, float]
    objects: tuple[ObjectPlan, ...]
    relations: tuple[Relation, ...]

    def as_report(self) -> dict:
        # Keep the in-memory return value identical to the persisted JSON.
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


@dataclass(frozen=True)
class MotionCues:
    guidance: np.ndarray
    visibility: float
    scale: float
    rotation_step: float
    opacity_fluctuation: float
    inertia: float
    noise_gain: float
    speed_limit: float
    beat: str


class SemanticLibrary:
    def __init__(self, path: Path = DEFAULT_CONFIG) -> None:
        self.path = Path(path).resolve()
        self.settings = json.loads(self.path.read_text(encoding="utf-8-sig"))
        self._validate()

    def _validate(self) -> None:
        config = self.settings
        for key in ("emotion_profiles", "exploration", "motion", "trace", "render",
                    "composition_rules", "role_rules", "cue_rules"):
            if key not in config:
                raise ValueError(f"Semantic config is missing {key}")
        def finite(value: Any) -> None:
            if isinstance(value, dict):
                for item in value.values(): finite(item)
            elif isinstance(value, list):
                for item in value: finite(item)
            elif isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError("Semantic parameters must be finite")
        finite(config)
        required = {"inertia", "noise_gain", "speed_limit", "opacity_fluctuation",
                    "rotation_flutter", "distance_variation"}
        for label, profile in config["emotion_profiles"].items():
            if set(profile) != required or any(not isinstance(v, list) or len(v) != 2 for v in profile.values()):
                raise ValueError(f"Invalid artistic emotion profile: {label}")
            if any(not 0 <= value < 1 for value in profile["inertia"]):
                raise ValueError("Emotion inertia must be in [0, 1)")
            if any(value < 0 for pair in profile.values() for value in pair):
                raise ValueError("Emotion profile values cannot be negative")
        for rule in config["role_rules"]:
            x0, x1, y0, y1 = rule["region"]
            if not 0.1 <= x0 < x1 <= 0.9 or not 0.1 <= y0 < y1 <= 0.9 or rule["scale"] <= 0:
                raise ValueError("Object preference regions must fit inside the viewport")
        if not 0 <= config["render"]["trace_alpha_max"] <= 32:
            raise ValueError("Trace alpha must be bounded below 13%")

    def plan(self, scene: SceneInput) -> ScenePlan:
        config = self.settings
        if scene.emotion_label not in config["emotion_profiles"]:
            raise ValueError(f"No artistic mapping for supplied emotion {scene.emotion_label!r}; add an explicit profile")
        profile = {key: values[0] + scene.emotion_intensity * (values[1] - values[0])
                   for key, values in config["emotion_profiles"][scene.emotion_label].items()}
        paragraphs = [part.strip() for part in scene.story.split("\n\n") if part.strip()]
        composition, composition_evidence, flow = "unspecified", "", (0.0, 0.0)
        for rule in config["composition_rules"]:
            evidence = next((text for text in (scene.title, *paragraphs)
                             if any(word in text for word in rule["keywords"])), None)
            if evidence is not None:
                composition, composition_evidence, flow = rule["name"], evidence, tuple(rule["flow"])
                break
        descriptions = []
        for obj in scene.objects:
            rule = next((rule for rule in config["role_rules"]
                         if any(alias in obj.name for alias in rule["aliases"])), None)
            aliases = tuple(rule["aliases"]) if rule else (obj.name,)
            # Composite names such as "서류철과 종이" also refer to the paper;
            # do not lose that explicitly listed part when choosing one role.
            aliases = tuple(dict.fromkeys((*aliases, *(alias for candidate in config["role_rules"]
                                                       for alias in candidate["aliases"] if alias in obj.name))))
            evidence = tuple(part for part in paragraphs if any(alias in part for alias in aliases))
            # A cue belongs to the object's own sentence. Paragraphs are used
            # only for co-reference in explicit source→target relationships.
            sentences = [sentence.strip() for paragraph in paragraphs for sentence in paragraph.split(".")
                         if any(alias in sentence for alias in aliases)]
            cues = tuple(cue for cue, words in config["cue_rules"].items() if rule and cue in rule["cues"]
                         and any(word in sentence for sentence in (obj.name, *sentences) for word in words))
            title_match = any(alias in scene.title for alias in aliases)
            explicit_focus = any("가장 먼저 눈" in sentence for sentence in sentences)
            occurrence = min((scene.story.find(alias) for alias in aliases if alias in scene.story), default=len(scene.story))
            descriptions.append((obj, rule, aliases, evidence, cues, (not explicit_focus, not title_match, occurrence, obj.index)))
        order = sorted(range(len(descriptions)), key=lambda index: descriptions[index][-1])
        objects = tuple(ObjectPlan(
            obj.object_id, obj.name, rule["role"] if rule else "unspecified", aliases,
            tuple(rule["region"]) if rule else (0.22, 0.78, 0.25, 0.75),
            rule["scale"] if rule else 1.0, order.index(index), cues, evidence,
        ) for index, (obj, rule, aliases, evidence, cues, _) in enumerate(descriptions))
        relations = []
        for index, obj in enumerate(objects):
            if obj.role not in {"figure", "hand"}:
                continue
            for target_index, target in enumerate(objects):
                if target_index == index or target.role not in {"journal", "record", "paper", "pool"}:
                    continue
                evidence = next((part for part in paragraphs
                                 if any(a in part for a in obj.aliases)
                                 and any(a in part for a in target.aliases)
                                 and any(word in part for word in config["cue_rules"]["approach"])), None)
                if evidence:
                    relations.append(Relation(index, target_index, evidence))
        return ScenePlan(scene.title, composition, composition_evidence, flow,
                         scene.emotion_label, scene.emotion_intensity, profile, objects, tuple(relations))


class SceneConditioning:
    def __init__(self, plan: ScenePlan, library: SemanticLibrary, duration: float, window: float) -> None:
        self.plan, self.settings = plan, library.settings
        self.duration, self.window = duration, window
        self.content_duration = max(1 / 30, duration - window)

    def initialize(self, agents: Sequence[Any]) -> None:
        for agent, obj in zip(agents, self.plan.objects):
            x0, x1, y0, y1 = obj.region
            agent.position = agent.rng.uniform((x0, y0), (x1, y1))
            agent.scale = obj.scale
            agent.rotation = float(agent.rng.uniform(-5, 5))
            agent.opacity = 0.0
            agent.energy = 0.0

    def beat(self, seconds: float) -> str:
        if seconds >= self.duration - self.window: return "Transition"
        fraction = seconds / self.content_duration
        if fraction < self.settings["motion"]["reveal_start"]: return "Establish"
        if fraction < self.settings["motion"]["interaction_start"]: return "Reveal"
        return "Interaction"

    def sample(self, index: int, positions: np.ndarray, seconds: float, phase: float) -> MotionCues:
        obj, profile = self.plan.objects[index], self.plan.emotion_parameters
        motion = self.settings["motion"]
        fraction = seconds / self.content_duration
        beat = self.beat(seconds)
        if obj.reveal_rank == 0:
            # The focal object can become visible during the preceding window;
            # its state is then kept at this scene's start, without a re-spawn.
            reveal = float(np.clip((seconds + self.window) / max(self.window * .7, 1 / 30), 0, 1))
        else:
            start = motion["reveal_start"] + (obj.reveal_rank - 1) * motion["reveal_step"]
            reveal = float(np.clip((fraction - start) / motion["reveal_duration_fraction"], 0, 1))
        reveal = reveal * reveal * (3 - 2 * reveal)
        position = positions[index]
        x0, x1, y0, y1 = obj.region
        # A soft region, never a target point. Inside it this term is zero.
        nearest = np.clip(position, (x0, y0), (x1, y1))
        guidance = np.clip((nearest - position) * 6.0, -.65, .65)
        guidance += np.asarray(self.plan.flow) * (.35 if obj.role in {"floor", "pool"} else 1.0)
        oscillation = math.sin(seconds * 2.1 + phase)
        if "falling" in obj.cues and obj.role not in {"floor", "pool"}:
            guidance[1] += .62
        if "floating" in obj.cues:
            guidance += (.14 * oscillation, -.27 * math.cos(seconds * .8 + phase))
        if "weight" in obj.cues:
            guidance[1] += .32 * math.sin(seconds * 1.1 + phase)
        if "flutter" in obj.cues:
            guidance[0] += .24 * oscillation
        interaction = float(np.clip((fraction - motion["interaction_start"]) / .2, 0, 1))
        for relation in self.plan.relations:
            if relation.source == index:
                delta = positions[relation.target] - position
                distance = float(np.linalg.norm(delta))
                preferred_gap = .18 + profile["distance_variation"] * math.sin(seconds * 1.7 + phase)
                if distance > preferred_gap:
                    guidance += interaction * motion["relation_strength"] * delta / max(distance, .01)
        # Readability keeps full sprites from staying exactly on top of one
        # another; it is a composition preference, not a collision simulation.
        for other_index, other in enumerate(positions):
            if other_index == index: continue
            delta = position - other
            distance = float(np.linalg.norm(delta))
            radius = motion["separation_distance"]
            if .001 < distance < radius:
                guidance += delta / distance * (radius - distance) / radius * .32
        norm = float(np.linalg.norm(guidance))
        guidance /= max(1., norm)
        flutter = profile["rotation_flutter"] * oscillation
        if "flutter" in obj.cues: flutter *= 1.6
        scale = obj.scale * (1 + .018 * self.plan.emotion_intensity * math.sin(seconds * 2.7 + phase))
        if "expansion" in obj.cues:
            scale *= 1 + .08 * interaction
        return MotionCues(guidance, reveal, scale, flutter, profile["opacity_fluctuation"],
                          profile["inertia"], profile["noise_gain"], profile["speed_limit"], beat)
