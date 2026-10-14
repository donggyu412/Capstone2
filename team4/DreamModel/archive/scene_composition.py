"""Build an explicitly approximate scene reference from supplied imagery.

The result is one image/field, not separately animated object layers. Layouts
are artistic, source-text-backed estimates, not Team3 camera/depth ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from PIL import Image, ImageFilter
from team4.DreamModel.archive.frame_renderer import load_background
from team4.DreamModel.runtime.input_loader import SceneInput
from team4.DreamModel.runtime.semantic_conditioning import SemanticLibrary, ScenePlan


@dataclass
class SceneComposition:
    rgb: np.ndarray
    reveal: np.ndarray
    labels: np.ndarray
    saliency: np.ndarray
    layout: list[dict]
    plan: ScenePlan


def build_composition(scene: SceneInput, width: int, height: int,
                      library: SemanticLibrary, placement_overrides: dict | None = None,
                      background_rgb: np.ndarray | None = None) -> SceneComposition:
    plan = library.plan(scene)
    plate = load_background(scene.background_path, width, height) if background_rgb is None else background_rgb
    canvas = Image.fromarray(plate).convert("RGBA")
    labels = np.zeros((height, width), dtype=np.int16)
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    distance = np.sqrt(((xx / width - .52) * .8)**2 + (yy / height - .46)**2)
    reveal = .012 + .10 * distance
    # x, y, fraction of viewport height, horizontal perspective scale, rotation.
    placements = {
        "journal": (.28, .73, .28, 1.1, -8),
        "pool": (.54, .85, .16, 1.8, 0),
        "droplet": (.55, .27, .14, 1.0, 0),
        "record": (.29, .57, .25, 1.0, -5),
        "paper": (.58, .61, .19, 1.0, 10),
        "figure": (.64 if plan.composition == "room" else .52, .39, .43, 1.0, 0),
        "floor": (.53, .85, .17, 1.7, 0),
        "hand": (.69, .57, .31, 1.0, -9),
        "unspecified": (.38, .62, .25, 1.0, 0),
    }
    layout = []
    # Depth order is a compositing estimate; the renderer never moves these PNGs.
    order = sorted(range(len(scene.objects)), key=lambda i: {"figure": 0, "floor": 1, "pool": 2}.get(plan.objects[i].role, 3))
    for index in order:
        obj, rule = scene.objects[index], plan.objects[index]
        x, y, size, perspective, angle = placements[rule.role]
        anchor = "role-based approximate depth"
        if rule.role == "record" and any("바닥" in p and "떨어" in p for p in rule.evidence):
            x, y, size, angle = .43, .77, .25, -12
            anchor = "source paragraph places the file at the floor"
        if placement_overrides and rule.role in placement_overrides:
            x, y, size, perspective, angle = placement_overrides[rule.role]
            anchor = "painterly spatial composition; artistic approximation"
        with Image.open(obj.path) as source:
            sprite = source.convert("RGBA")
            box = sprite.getchannel("A").getbbox()
            if box:
                sprite = sprite.crop(box)
            h = max(2, round(height * size))
            w = max(2, round(h * sprite.width / sprite.height * perspective))
            sprite = sprite.resize((w, h), Image.Resampling.LANCZOS)
            sprite = sprite.rotate(angle, Image.Resampling.BICUBIC, expand=True)
        left, top = round(x * width - sprite.width / 2), round(y * height - sprite.height / 2)
        layer = Image.new("RGBA", (width, height))
        layer.paste(sprite, (left, top))  # preserve RGBA: do not apply alpha twice
        alpha = np.asarray(layer.getchannel("A"), dtype=np.float32) / 255
        # A restrained contact shadow connects supplied shapes to the same space.
        if rule.role in {"journal", "record", "floor", "pool"}:
            shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            shadow_alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(max(1, height * .008)))
            shadow.putalpha(shadow_alpha.point(lambda v: round(v * .22)))
            canvas = Image.alpha_composite(canvas, shadow)
        canvas = Image.alpha_composite(canvas, layer)
        occupied = alpha > .20
        labels[occupied] = index + 1
        reveal[occupied] = .10 + .075 * rule.reveal_rank
        layout.append({
            "object_id": obj.object_id, "name": obj.name, "role": rule.role,
            "center_normalized": [x, y], "height_fraction": size,
            "horizontal_projection_scale": perspective, "rotation_degrees": angle,
            "reveal_rank": rule.reveal_rank, "anchor_basis": anchor,
            "evidence": list(rule.evidence),
            "status": "DreamModel approximation; no upstream object layout supplied",
        })
    rgb = np.asarray(canvas.convert("RGB"), dtype=np.float32) / 255
    luminance = rgb @ np.array([.2126, .7152, .0722], dtype=np.float32)
    gy, gx = np.gradient(luminance)
    saliency = .35 + luminance + 2 * np.sqrt(gx*gx + gy*gy) + .35 * (labels > 0)
    return SceneComposition(rgb, reveal.astype(np.float32), labels, saliency, layout, plan)
