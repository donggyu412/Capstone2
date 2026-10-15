"""Lossy visual grammar. No source RGB image survives into the renderer.

Contours become short, normalized turn/length programs; positions, palette
and direction histograms are soft conditions, never pixel targets.
"""
from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np
from PIL import Image
from team4.DreamModel.runtime.input_loader import SceneInput
from team4.DreamModel.runtime.semantic_conditioning import SemanticLibrary


def palette(rgb, mask=None):
    pixels = rgb.reshape(-1, 3) if mask is None else rgb[mask]
    if not len(pixels):
        pixels = np.array([[.3, .35, .4]])
    codes = (np.clip(pixels * 5, 0, 4).astype(int) * (25, 5, 1)).sum(axis=1)
    groups, counts = np.unique(codes, return_counts=True)
    colors = np.array([pixels[codes == k].mean(axis=0) for k in groups[np.argsort(counts)[-4:]]])
    # Lift exposure in HSV to retain the dark source's teal/copper chroma.
    # This is one fixed material transform, independent of emotion.
    hsv = cv2.cvtColor(colors.astype('float32')[None], cv2.COLOR_RGB2HSV)
    hsv[:,:,2] = np.clip(np.sqrt(hsv[:,:,2]), .32, .92)
    colors = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)[0].astype(float)
    return colors


@dataclass
class Motif:
    family: str
    name: str
    kind: str
    path: np.ndarray
    closed: bool
    center: np.ndarray
    extent: np.ndarray
    colors: np.ndarray
    salience_time: float
    evidence: tuple[str, ...]
    source: str
    veins: tuple = ()


class MemoryField:
    def __init__(self, scene: SceneInput, library: SemanticLibrary):
        self.scene = scene
        self.plan = library.plan(scene)
        image = np.asarray(Image.open(scene.background_path).convert('RGB').resize((240, 135))) / 255.
        self.colors = palette(image)
        gray = cv2.cvtColor((image * 255).astype('uint8'), cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 1)
        dx, dy = cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)
        self.direction = np.arctan2(dy, dx) + np.pi / 2
        self.strength = np.hypot(dx, dy)
        # Fixed statistics, not a CA state or an image reconstruction field.
        self.orientation_histogram = np.histogram(self.direction % np.pi, bins=12,
            range=(0, np.pi), weights=self.strength)[0]
        self.orientation_histogram /= max(self.orientation_histogram.sum(), 1)
        self.region_energy = cv2.resize(self.strength, (8, 5), interpolation=cv2.INTER_AREA)
        self.region_energy /= max(self.region_energy.max(), 1)
        structural = cv2.GaussianBlur(gray, (9, 9), 2.3)
        structural = cv2.createCLAHE(clipLimit=2, tileGridSize=(4, 3)).apply(structural)
        lines = cv2.HoughLinesP(cv2.Canny(structural, 22, 60), 1, np.pi / 180, 18,
                                minLineLength=28, maxLineGap=25)
        pairs = [] if lines is None else [x.reshape(2, 2) / (240, 135) for x in lines.reshape(-1, 4)]
        pairs.sort(key=lambda x: -np.linalg.norm(x[1] - x[0]))
        selected = []
        for pair in pairs:
            if all(np.linalg.norm(pair.mean(axis=0) - p.mean(axis=0)) > .09 for p in selected):
                selected.append(pair)
            if len(selected) == 12:
                break
        self.motifs = []
        paired = set()
        # Two compatible directional tendencies define a broad spatial membrane.
        # This retains a suggestion of walls/floor instead of isolated bright bars.
        for i, first in enumerate(selected):
            if i in paired:
                continue
            axis = first[1]-first[0]
            axis /= max(np.linalg.norm(axis), .001)
            for j, second in enumerate(selected):
                if j <= i or j in paired:
                    continue
                other = second[1]-second[0]
                parallel = abs(float(axis @ other)) / max(np.linalg.norm(other), .001)
                gap = abs(float((second.mean(axis=0)-first.mean(axis=0)) @ np.array([-axis[1],axis[0]])))
                if parallel > .88 and .10 < gap < .65:
                    ordered = second if axis @ other > 0 else second[::-1]
                    world = np.array([first[0], first[1], ordered[1], ordered[0]])
                    center = world.mean(axis=0)
                    extent = max(np.ptp(world,axis=0).max(),.1)
                    self.motifs.append(Motif('space',f'spatial membrane {i}-{j}','space',
                        (world-center)/extent,True,center,np.array([extent,extent]),
                        self.colors,.12,(),str(scene.background_path)))
                    paired.update((i,j))
                    break
        for i, pair in enumerate(selected):
            if i in paired:
                continue
            center = pair.mean(axis=0)
            delta = pair[1] - pair[0]
            norm = max(float(np.linalg.norm(delta)), .1)
            tangent = np.array([-delta[1], delta[0]]) / norm
            # Four coarse controls with a curved memory deviation, not Hough replay.
            points = np.array([-.5 * delta, -.17 * delta + tangent * .008,
                               .17 * delta - tangent * .006, .5 * delta])
            self.motifs.append(Motif('space', f'spatial tendency {i}', 'space', points / norm,
                False, center, np.array([norm, norm]), self.colors, .12, (), str(scene.background_path)))
        for obj, plan in zip(scene.objects, self.plan.objects):
            rgba = np.asarray(Image.open(obj.path).convert('RGBA'))
            alpha = (rgba[:, :, 3] > 80).astype('uint8') * 255
            contours, _ = cv2.findContours(alpha, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contour = max(contours, key=cv2.contourArea)
            perimeter = cv2.arcLength(contour, True)
            simple = cv2.approxPolyDP(contour, perimeter * .008, True)[:, 0].astype(float)
            if len(simple) > 40:
                simple = simple[np.linspace(0, len(simple) - 1, 40).astype(int)]
            lo, hi = simple.min(axis=0), simple.max(axis=0)
            points = (simple - (lo + hi) * .5) / max((hi - lo).max(), 1)
            x0, x1, y0, y1 = plan.region
            center = np.array([(x0 + x1) * .5, (y0 + y1) * .5])
            # Metadata has no placement. These are explicit artistic regions.
            center[0] += (plan.reveal_rank - (len(scene.objects) - 1) / 2) * .16
            center = np.clip(center, (.17, .25), (.83, .8))
            extent = np.array([.30, .53]) * (1.12 if plan.role in ('figure', 'hand') else 1.)
            if plan.role in ('floor', 'pool'):
                extent *= (1.25, .58)
            first = min((scene.story.find(a) for a in plan.aliases if a in scene.story), default=0)
            salience_time = .18 + .48 * first / max(1, len(scene.story))
            inner = cv2.Canny(cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2GRAY), 65, 145)
            inner[cv2.erode(alpha, np.ones((17,17), np.uint8)) == 0] = 0
            raw_lines = cv2.HoughLinesP(inner, 1, np.pi / 180, 35, minLineLength=65, maxLineGap=15)
            veins = []
            if raw_lines is not None:
                for edge in sorted(raw_lines.reshape(-1,4), key=lambda e: -np.linalg.norm(e[:2]-e[2:])):
                    v = (edge.reshape(2,2) - (lo+hi)*.5) / max((hi-lo).max(), 1)
                    if all(np.linalg.norm(v.mean(axis=0)-old.mean(axis=0)) > .12 for old in veins):
                        veins.append(v)
                    if len(veins) >= 4: break
            self.motifs.append(Motif(obj.object_id, obj.name, plan.role, points, True,
                center, extent, palette(rgba[:, :, :3] / 255., alpha > 0), salience_time,
                plan.evidence, str(obj.path), tuple(veins)))
        if not self.motifs:
            raise ValueError('No geometric memory could be extracted')

    def support(self, position, direction):
        x, y = np.clip((np.asarray(position) * (8, 5)).astype(int), (0, 0), (7, 4))
        angle = np.arctan2(direction[1], direction[0]) % np.pi
        bucket = min(11, int(angle / np.pi * 12))
        return float(.5 * self.region_energy[y, x] + .5 * min(1, self.orientation_histogram[bucket] * 6))

    def salience(self, motif, phase, enabled=True):
        if not enabled or motif.family == 'space':
            return .5
        if not motif.evidence:
            return .3
        return float(.18 + .82 * np.exp(-((phase - motif.salience_time) / .25) ** 2))

    def report(self):
        return {'scene_id': self.scene.scene_id, 'orientation_histogram': self.orientation_histogram.tolist(),
            'motifs': [{'family': m.family, 'name': m.name, 'kind': m.kind, 'controls': len(m.path),
                        'region_center': m.center.tolist(), 'extent': m.extent.tolist(),
                        'salience_time': m.salience_time, 'evidence': m.evidence, 'source': m.source}
                       for m in self.motifs],
            'placement': 'artistic approximation; no upstream coordinates',
            'renderer_receives_source_images': False}
