"""Memory-conditioned growth and selection of actual geometric graphs.

The population is deliberately bounded. This is an open-ended research
prototype with a finite grammar, not evidence of unbounded creative evolution.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import Counter
import math
import cv2
import numpy as np
from .memory_grammar import MemoryField, Motif
from .audience import AudienceAtmosphere


@dataclass(eq=False)
class Organism:
    uid: int
    motif: Motif
    primitives: list[str]
    controlPoints: np.ndarray
    connections: list[tuple[int, int]]
    position: np.ndarray
    scale: np.ndarray
    orientation: float
    colorTraits: np.ndarray
    age: float
    energy: float
    persistence: float
    memoryAffinity: float
    lineage: tuple[int, ...]
    rest: np.ndarray
    born_scene: int
    cursor: int = 2
    growth: float = 0.
    dying: bool = False
    opacity: float = 0.
    closed: bool = False
    faces: list[list[int]] = field(default_factory=list)
    fitness: float = .5
    novelty: float = 1.
    diversity: float = 1.
    mutations: int = 0
    inherited: bool = False
    membraneOpacity: float = 0.

    def descriptor(self):
        p = self.rest
        degrees = Counter(k for edge in self.connections for k in edge)
        span = np.maximum(np.ptp(p, axis=0), .01)
        edges = np.array([p[b] - p[a] for a, b in self.connections])
        directions = np.arctan2(edges[:, 1], edges[:, 0]) if len(edges) else np.zeros(1)
        return np.array([len(p) / 65, len(self.connections) / max(1, len(p)) / 2,
            sum(d > 2 for d in degrees.values()) / max(1, len(p)), float(self.closed),
            span[0] / span.sum(), np.std(directions) / np.pi,
            min(1, self.mutations / 8), min(1, len(self.lineage) / 8)])


class Evolution:
    def __init__(self, memories, seed=101, *, story=True, emotion=True, sound=True,atmosphere=None):
        self.memories = memories
        self.rng = np.random.default_rng(seed)
        self.enabled = {'story': story, 'emotion': emotion, 'sound': sound}
        self.atmosphere=atmosphere or AudienceAtmosphere()
        self.spatial_field=None
        self.population = []
        self.archive = []
        self.events = []
        self.transfers = []
        self.next_id = 0
        self.scene_index = -1
        self.time = 0.
        self.tick = 0
        self.selection_elapsed = 0.
        self.birth_credit = 0.
        self.merge_credit = 0.
        self.audio = np.zeros(2)
        self.emotion = 0.
        self.memory = memories[0]
        self.phase = 0.
        self.born_families = Counter()
        self.retained_ids = set()

    def event(self, kind, ids, **kwargs):
        self.events.append({'time': round(self.time, 4), 'scene': self.scene_index + 1,
                            'type': kind, 'ids': list(ids), **kwargs})

    def enter_scene(self, index):
        old = self.memory
        alive = [o for o in self.population if not o.dying and o.energy > .1]
        survivors = sorted(alive, key=lambda o: o.fitness + o.novelty + o.persistence, reverse=True)[:5]
        self.scene_index = index
        self.memory = self.memories[index]
        self.born_families.clear()
        self.retained_ids.clear()
        self.birth_credit = .8
        self.merge_credit = 0.
        if not index:
            return
        for o in self.population:
            if o not in survivors:
                self.kill(o, 'scene selection')
        for o in survivors:
            o.inherited = True
            o.persistence = min(1., o.persistence + .15)
            o.energy = max(o.energy, .7)
            self.archive.append(o.descriptor())
        self.transfers.append({'from_scene': old.scene.scene_id, 'into_scene': self.memory.scene.scene_id,
            'survivors': [{'id': o.uid, 'lineage': list(o.lineage), 'nodes': len(o.rest),
                            'color': o.colorTraits.tolist(), 'persistence': o.persistence,
                            'position': o.position.tolist(), 'family': o.motif.family} for o in survivors]})
        self.event('inheritance', [o.uid for o in survivors])

    def choose_motif(self):
        motifs = self.memory.motifs
        weights = []
        for m in motifs:
            prior = 1.0 if m.family == 'space' else 5.0
            salience = self.memory.salience(m, self.phase, self.enabled['story'])
            count = sum(o.motif.family == m.family and not o.dying for o in self.population)
            duplicate = sum(o.motif.name == m.name and not o.dying for o in self.population)
            weights.append(prior * (.12 + salience ** 2 * 2.2) / (1 + count * .15) * (.015 if duplicate else 1))
        weights = np.array(weights)
        return motifs[int(self.rng.choice(len(motifs), p=weights / weights.sum()))]

    def birth(self, motif=None):
        m = motif or self.choose_motif()
        self.next_id += 1
        center = m.center + self.rng.normal(0, .014 if m.family != 'space' else .018, 2)
        scale = m.extent * self.rng.uniform(.87, 1.1, 2)
        orientation = float(self.rng.normal(0, .045))
        rotation = np.array([[np.cos(orientation), -np.sin(orientation)],
                             [np.sin(orientation), np.cos(orientation)]])
        start = center + (m.path[0] * scale) @ rotation.T
        delta = (m.path[1] - m.path[0]) * scale @ rotation.T
        rest = np.array([start, start + delta * self.rng.uniform(.92, 1.06)])
        spatial_color = self.memory.colors[np.argmax(np.ptp(self.memory.colors, axis=1))]
        colors = m.colors[int(self.rng.integers(len(m.colors)))] * .62 + spatial_color * .38
        o = Organism(self.next_id, m, ['point', 'curve'], np.array([start, start.copy()]),
            [(0, 1)], center, scale, orientation, colors, 0., .8, .45, .7,
            (self.next_id,), rest, self.scene_index, opacity=0.)
        self.population.append(o)
        self.born_families[m.family] += 1
        self.event('birth', [o.uid], family=m.family)
        return o

    def grow(self, o):
        if o.cursor >= len(o.motif.path):
            if o.motif.closed and not o.closed:
                o.connections.append((o.cursor - 1, 0))
                o.faces.append(list(range(o.cursor)))
                o.closed = True
                o.primitives.append('membrane')
                for vein in o.motif.veins:
                    if self.rng.random() > .8:
                        continue
                    segment = o.position + vein * o.scale
                    n = len(o.rest)
                    nearest = int(np.argmin(np.linalg.norm(o.rest-segment[0], axis=1)))
                    o.rest = np.vstack((o.rest, segment))
                    o.controlPoints = np.vstack((o.controlPoints, o.controlPoints[nearest], o.controlPoints[nearest]))
                    o.connections.extend([(nearest,n),(n,n+1)])
                self.event('closure', [o.uid])
            return
        a = o.cursor - 1
        delta = (o.motif.path[o.cursor] - o.motif.path[a]) * o.scale
        angle = o.orientation + self.rng.normal(0, .075 + .12 * self.emotion)
        c, s = np.cos(angle), np.sin(angle)
        delta = delta @ np.array([[c, s], [-s, c]]) * self.rng.uniform(.96, 1.04)
        # Build from the previous growth tip, never attract to source positions.
        point = o.rest[a] + delta
        idx = len(o.rest)
        o.rest = np.vstack((o.rest, point))
        o.controlPoints = np.vstack((o.controlPoints, o.controlPoints[a]))
        o.connections.append((a, idx))
        o.cursor += 1
        self.event('growth', [o.uid], nodes=len(o.rest))

    def mutate(self, o, operation=None):
        if len(o.rest) < 3 or len(o.rest) > 64:
            return
        op = operation or str(self.rng.choice(['bend', 'branch', 'split'], p=[.40, .35, .25]))
        o.mutations += 1
        if op == 'bend':
            i = int(self.rng.integers(1, len(o.rest)))
            o.rest[i] += self.rng.normal(0, .005 + .006 * self.emotion, 2)
        elif op == 'branch':
            a = int(self.rng.integers(0, len(o.rest)))
            b = max(0, a - 1)
            tangent = o.rest[a] - o.rest[b]
            if np.linalg.norm(tangent) < .001:
                tangent = np.array([.02, .02])
            normal = np.array([-tangent[1], tangent[0]])
            normal *= .035 / max(np.linalg.norm(normal), .001)
            i = len(o.rest)
            o.rest = np.vstack((o.rest, o.rest[a] + normal, o.rest[a] + normal * 1.5 + tangent * .4))
            o.controlPoints = np.vstack((o.controlPoints, o.controlPoints[a], o.controlPoints[a]))
            o.connections.extend([(a, i), (i, i + 1)])
            o.primitives.append('branch')
        else:
            e = int(self.rng.integers(len(o.connections)))
            a, b = o.connections.pop(e)
            i = len(o.rest)
            point = (o.rest[a] + o.rest[b]) * .5 + self.rng.normal(0, .008, 2)
            o.rest = np.vstack((o.rest, point))
            o.controlPoints = np.vstack((o.controlPoints, (o.controlPoints[a] + o.controlPoints[b]) * .5))
            o.connections.extend([(a, i), (i, b)])
        self.event('mutation', [o.uid], operation=op, nodes=len(o.rest))

    def combine(self, a, b, recombination=False):
        # Transfer a branch from the second parent's actual graph into the first.
        # No image/opacity blend is used to represent genetic exchange.
        if len(a.rest) > 60 or len(b.rest) < 3:
            return False
        dist = np.linalg.norm(a.rest[:, None] - b.rest[None, :], axis=2)
        ai, bi = np.unravel_index(np.argmin(dist), dist.shape)
        selected = [int(bi)]
        edges = []
        for _ in range(5):
            next_edge = next(((x, y) if x in selected else (y, x)
                for x, y in b.connections if (x in selected) != (y in selected)), None)
            if next_edge is None:
                break
            x, y = next_edge
            edges.append((x, y))
            selected.append(y)
        n = len(a.rest)
        transferred = b.rest[selected].copy()
        transferred += (a.rest[ai] - transferred[0]) * .72
        mapping = {old: n + k for k, old in enumerate(selected)}
        a.rest = np.vstack((a.rest, transferred))
        a.controlPoints = np.vstack((a.controlPoints, np.tile(a.controlPoints[ai], (len(selected), 1))))
        a.connections.append((int(ai), n))
        a.connections.extend((mapping[x], mapping[y]) for x, y in edges)
        a.lineage = tuple(sorted(set((*a.lineage, *b.lineage))))
        a.colorTraits = a.colorTraits * .70 + b.colorTraits * .30
        a.persistence = min(1., a.persistence * .7 + b.persistence * .3 + .08)
        a.primitives.append('recombined branch' if recombination else 'composite')
        self.event('recombination' if recombination else 'combination', [a.uid, b.uid],
                   inherited_nodes=len(selected), lineage=list(a.lineage))
        self.kill(b, 'donated structure')
        return True

    def kill(self, o, reason):
        if not o.dying:
            o.dying = True
            self.event('extinction_start', [o.uid], reason=reason)

    def select(self):
        live = [o for o in self.population if not o.dying]
        counts = Counter(o.motif.family for o in live)
        descriptors = [o.descriptor() for o in live]
        references = descriptors + self.archive[-60:]
        for i, o in enumerate(live):
            d = descriptors[i]
            distances = [float(np.linalg.norm(d - x)) for j, x in enumerate(references) if i != j]
            o.novelty = min(1., (float(np.mean(sorted(distances)[:4])) if distances else 1.) * 2.5)
            span = np.ptp(o.rest, axis=0)
            base_span = np.ptp(o.motif.path * o.scale, axis=0)
            proportion = math.exp(-abs(math.log((span[0] + .02) / (span[1] + .02)) -
                                           math.log((base_span[0] + .02) / (base_span[1] + .02))))
            region = math.exp(-np.linalg.norm(o.rest.mean(axis=0) - o.motif.center) * 2.5)
            o.memoryAffinity = float(.55 * proportion + .45 * region)
            support = self.memory.support(o.position, o.rest[-1] - o.rest[0])
            if self.spatial_field is not None:
                h,w=self.spatial_field.shape
                x,y=np.clip((o.position*(w,h)).astype(int),(0,0),(w-1,h-1))
                support=.65*support+.35*float(self.spatial_field[y,x])
            bounds = float(np.mean(np.all((o.rest >= -.08) & (o.rest <= 1.08), axis=1)))
            salience = self.memory.salience(o.motif, self.phase, self.enabled['story'])
            o.fitness = .38 * o.memoryAffinity + .18 * support + .20 * bounds + .24 * salience
            o.diversity = 1. / counts[o.motif.family]
            merit = .50 * o.fitness + .30 * o.novelty + .20 * o.diversity
            # Actual survival decision, not a diagnostic score only.
            o.energy += (merit - (.48 + .08 * self.emotion)) * .34
            o.persistence = float(np.clip(o.persistence + (merit - .5) * .05
                + (self.atmosphere.coherence-.5)*.008, .1, 1))
            if o.age > 1.0 and (o.energy < .20 or (merit < .48 and self.rng.random() < .30)):
                self.kill(o, 'fitness novelty diversity selection')
        if len(live) > 23:
            for o in sorted(live, key=lambda a: a.fitness * .5 + a.novelty * .3 + a.diversity * .2)[:len(live)-23]:
                self.kill(o, 'population competition')
        if live:
            best = max(live, key=lambda o: o.fitness + o.novelty)
            self.archive.append(best.descriptor())

    def step(self, phase, dt, rms=0., onset=0.):
        self.phase = phase
        self.time += dt
        self.tick += 1
        # Stable low-pass on the real audio envelope; never drive displacement directly.
        target_audio = np.array([rms, onset]) if self.enabled['sound'] else np.zeros(2)
        self.audio += (target_audio - self.audio) * (1 - math.exp(-dt / .22))
        label = self.memory.scene.emotion_label
        if label != '공포':
            raise ValueError('Geometric emotion profile is only defined for supplied 공포; add an explicit artistic profile')
        self.emotion = self.memory.scene.emotion_intensity if self.enabled['emotion'] else 0.
        active = [o for o in self.population if not o.dying]
        if phase > .76 and not self.retained_ids:
            self.retained_ids = {o.uid for o in sorted(active,
                key=lambda a: a.fitness + a.novelty + a.persistence, reverse=True)[:5]}
        birth_rate = (2.2 + 2.0 * self.audio[0] + 1.5 * self.audio[1]) * (1 if phase < .70 else .10)
        birth_rate *= .8+.4*self.atmosphere.arousal
        self.birth_credit += dt * birth_rate
        while self.birth_credit >= 1 and len(active) < 24:
            self.birth_credit -= 1
            active.append(self.birth())
        for o in list(self.population):
            o.age += dt
            if o.dying:
                o.energy *= math.exp(-dt * (1.4 + self.emotion * .5))
                o.opacity *= math.exp(-dt * 2.8)
                o.membraneOpacity *= math.exp(-dt * 4.0)
                # Tips shrink toward connected parents; surfaces vanish before contours.
                for a, b in o.connections:
                    o.rest[b] += (o.rest[a] - o.rest[b]) * dt * .12
                if o.opacity < .008:
                    self.population.remove(o)
                    self.event('extinction', [o.uid])
                    continue
            else:
                o.opacity += (min(1, o.energy + .20) - o.opacity) * dt * 3.3
                o.membraneOpacity += (o.opacity - o.membraneOpacity) * dt * 2.4
                salience = self.memory.salience(o.motif, phase, self.enabled['story'])
                o.growth += dt * (len(o.motif.path) / 1.35) * (.65 + .65 * salience + .65 * self.audio[0])
                # Complete the primary chain before mutations may insert branch nodes.
                while o.growth >= 1:
                    o.growth -= 1
                    self.grow(o)
                if o.cursor >= len(o.motif.path) and self.rng.random() < dt * (.08 + .48 * self.emotion + .45 * self.audio[1])*(.75+.5*self.atmosphere.tension):
                    self.mutate(o)
                if phase > .79 and not o.inherited and o.uid not in self.retained_ids:
                    self.kill(o, 'late scene dissolution')
            o.controlPoints += (o.rest - o.controlPoints) * (1 - math.exp(-dt * 9))
            o.position = o.controlPoints.mean(axis=0)
        self.merge_credit += dt * (.20 + .55 * self.audio[0] + .25 * self.emotion)
        if self.merge_credit >= 1 and phase > .22:
            self.merge_credit -= 1
            candidates = [o for o in self.population if not o.dying and o.age > .65
                          and o.cursor >= len(o.motif.path) and len(o.rest) < 60]
            pairs = [(a, b) for i, a in enumerate(candidates) for b in candidates[i+1:]
                     if a.motif.family != b.motif.family and np.linalg.norm(a.position-b.position) < .42]
            if pairs:
                # Inherited graphs preferentially mate with newly born memory graphs.
                pairs.sort(key=lambda ab: (not (ab[0].born_scene != ab[1].born_scene),
                                          np.linalg.norm(ab[0].position-ab[1].position)))
                a, b = pairs[0]
                if a.born_scene < b.born_scene:
                    a, b = b, a
                self.combine(a, b, a.born_scene != b.born_scene)
        self.selection_elapsed += dt
        if self.selection_elapsed + 1e-9 >= .4:
            self.selection_elapsed = max(0.,self.selection_elapsed-.4)
            self.select()

    def snapshot(self):
        live = [o for o in self.population if not o.dying]
        counts = Counter(o.motif.family for o in live)
        p = np.array(list(counts.values()), float) / max(1, len(live))
        return {'live': len(live), 'dying': sum(o.dying for o in self.population),
            'nodes': sum(len(o.rest) for o in self.population),
            'branches': sum(o.primitives.count('branch') for o in self.population),
            'family_entropy': float(-np.sum(p * np.log(p + 1e-10))),
            'fitness': float(np.mean([o.fitness for o in live])) if live else 0.,
            'novelty': float(np.mean([o.novelty for o in live])) if live else 0.,
            'audio_rms': float(self.audio[0]), 'emotion_intensity': self.emotion,
            'families': dict(counts)}


def smooth_path(points, iterations=2, closed=False):
    points = np.asarray(points, dtype=float)
    if len(points) < 3:
        return points
    for _ in range(iterations):
        a, b = (points, np.roll(points, -1, axis=0)) if closed else (points[:-1], points[1:])
        p = np.empty((len(a) * 2, 2))
        p[0::2], p[1::2] = a * .8 + b * .2, a * .2 + b * .8
        points = p if closed else np.vstack((points[0], p, points[-1]))
    return points


class GeometricRenderer:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.wh = np.array([width, height])

    def render(self, evolution):
        # Only graph states and palette statistics enter the renderer.
        canvas = np.empty((self.height, self.width, 3), dtype=np.float32)
        canvas[:] = np.array([.018, .025, .033])
        surfaces = np.zeros_like(canvas)
        strokes = np.zeros_like(canvas)
        for o in sorted(evolution.population, key=lambda x: x.motif.family != 'space'):
            pts = o.controlPoints * self.wh
            color = np.clip(o.colorTraits, 0, 1)
            alpha = o.opacity
            thickness = max(1, round(self.width / 680))
            if o.motif.family == 'space' and not o.closed and len(pts) >= 3:
                curve = smooth_path(pts[:o.cursor], 3)
                tangent = curve[-1]-curve[0]
                offset = np.array([-tangent[1],tangent[0]]) / max(np.linalg.norm(tangent),1)
                offset *= self.height * .030 * o.energy
                ribbon = np.vstack((curve, (curve + offset)[::-1])).astype(np.int32)
                cv2.fillPoly(surfaces, [ribbon], tuple(color * o.membraneOpacity * .36), lineType=cv2.LINE_AA)
            for face in o.faces:
                curve = smooth_path(pts[face], 2, True).astype(np.int32)
                fill = o.membraneOpacity ** 2 * (.24 if o.motif.family=='space' else .55) * min(1, max(0, o.age - .7))
                cv2.fillPoly(surfaces, [curve], tuple(color * fill), lineType=cv2.LINE_AA)
                cv2.polylines(strokes, [curve], True, tuple(color * alpha * .85), thickness, cv2.LINE_AA)
            # Walk graph chains rather than draw a cloud of samples.
            used = set()
            adjacency = {}
            for a, b in o.connections:
                adjacency.setdefault(a, []).append(b)
                adjacency.setdefault(b, []).append(a)
            for a, b in o.connections:
                key = tuple(sorted((a, b)))
                if key in used:
                    continue
                chain = [a, b]
                used.add(key)
                while len(adjacency.get(chain[-1], [])) == 2:
                    next_nodes = [n for n in adjacency[chain[-1]] if tuple(sorted((chain[-1], n))) not in used]
                    if not next_nodes:
                        break
                    n = next_nodes[0]
                    used.add(tuple(sorted((chain[-1], n))))
                    chain.append(n)
                path = smooth_path(pts[chain], 2).astype(np.int32)
                cv2.polylines(strokes, [path], False, tuple(color * alpha * .85), thickness, cv2.LINE_AA)
            if o.age < .25:
                cv2.circle(strokes, tuple(pts[0].astype(int)), 2, tuple(color * alpha), -1, cv2.LINE_AA)
        # Local halo around geometric ink, never an image reveal or temporal crossfade.
        halo = cv2.GaussianBlur(strokes, (0, 0), 3) * .22
        canvas += surfaces + strokes + halo
        return (np.clip(canvas, 0, 1) * 255).astype(np.uint8)
