"""Read the shared Team3 input contract without deriving story or emotion.

``scenes.json.act`` joins ``dream_scenes.json.scene`` and
``objects.json.scene``. The ordered stage labels come exclusively from
``scenes.json``. Optional manifest ``audio`` strings (or ``{"file": ...}``)
are relative to the containing manifest, and must stay inside shared input.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from PIL import Image, UnidentifiedImageError


STAGES = frozenset({"기", "승", "전", "결"})
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".ogg", ".flac", ".m4a"})


@dataclass(frozen=True)
class ObjectInput:
    scene_id: int
    index: int
    name: str
    path: Path

    @property
    def object_id(self) -> str:
        return f"{self.scene_id}:{self.index}"


@dataclass(frozen=True)
class SceneInput:
    scene_id: int
    stage: str
    title: str
    emotion_label: str
    emotion_intensity: float
    story: str
    background_path: Path
    objects: tuple[ObjectInput, ...]
    physics_laws: tuple[str, ...] = ()


@dataclass(frozen=True)
class InputBundle:
    scenes: tuple[SceneInput, ...]
    input_files: tuple[Path, ...]
    audio_path: Path | None
    warnings: tuple[str, ...]


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read input manifest {path}: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("scenes"), list):
        raise ValueError(f"{path.name} must contain a scenes array.")
    return value


def _scene_map(manifest: dict[str, Any], key: str, filename: str) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in manifest["scenes"]:
        if not isinstance(item, dict):
            raise ValueError(f"{filename}: each scene must be an object.")
        scene_id = item.get(key)
        if type(scene_id) is not int or scene_id < 1:
            raise ValueError(f"{filename}: {key} must be an explicit positive integer.")
        if scene_id in result:
            raise ValueError(f"{filename}: duplicate scene ID {scene_id}.")
        result[scene_id] = item
    if len(result) != 4:
        raise ValueError(f"{filename}: expected 4 unique scenes, found {len(result)}.")
    return result


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string.")
    return value


def _intensity(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number in [0, 1].")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} must be a finite number in [0, 1].")
    return result


def _asset_path(base: Path, value: Any, field: str, containment_root: Path | None = None) -> Path:
    reference = _text(value, field)
    # Reject Windows absolute paths on every platform, including test runners.
    winpath = PureWindowsPath(reference)
    if Path(reference).is_absolute() or winpath.drive or winpath.root or "://" in reference:
        raise ValueError(f"{field}: expected a relative input path, got {reference!r}.")
    root = (containment_root or base).resolve()
    try:
        path = (base / reference).resolve()
        path.relative_to(root)
    except (ValueError, OSError) as error:
        raise ValueError(f"{field}: path must stay inside {root}.") from error
    if not path.is_file():
        raise ValueError(f"{field}: input file does not exist: {path}")
    return path


def _validate_image(path: Path, *, object_image: bool, warnings: list[str]) -> None:
    # Pillow opens Unicode Paths directly; never rename a Korean input filename.
    try:
        with Image.open(path) as image:
            image.load()
            if image.width < 1 or image.height < 1:
                raise ValueError(f"Image has invalid dimensions: {path}")
            if object_image:
                if image.format != "PNG" or image.mode != "RGBA":
                    raise ValueError(f"Object image must be an RGBA PNG: {path}")
                minimum, maximum = image.getchannel("A").getextrema()
                if minimum == 255 or maximum == 0:
                    raise ValueError(f"Object image needs visible content and a transparent background: {path}")
                if image.size != (512, 512):
                    warnings.append(f"Object {path.name} is {image.width}x{image.height}; expected upstream default 512x512.")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError(f"Cannot decode input image {path}: {error}") from error


def _audio_file(path: Path) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"Audio input file does not exist: {path}")
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio format: {path.suffix}; use WAV, MP3, OGG, FLAC or M4A.")
    return path


def _select_audio(root: Path, manifests: tuple[tuple[Path, dict[str, Any]], ...], explicit: Path | None) -> Path | None:
    if explicit is not None:
        return _audio_file(Path(explicit))
    referenced: set[Path] = set()
    for manifest_path, manifest in manifests:
        for item in (manifest, *manifest["scenes"]):
            reference = item.get("audio")
            if reference is None or reference == "":
                continue
            if isinstance(reference, dict):
                if set(reference) != {"file"}:
                    raise ValueError(f"{manifest_path.name}: audio objects must contain only file; use --audio for an explicit full-length track.")
                reference = reference["file"]
            path = _asset_path(manifest_path.parent, reference, f"{manifest_path.name}.audio", root)
            referenced.add(_audio_file(path))
    if len(referenced) > 1:
        raise ValueError("Different per-scene audio tracks are not supported; use --audio with one full-length track.")
    if referenced:
        return next(iter(referenced))
    candidates: set[Path] = set()
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            resolved = path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise ValueError(f"Discovered audio must stay inside shared input: {path}") from error
            candidates.add(resolved)
    if len(candidates) > 1:
        raise ValueError("Multiple audio files found under shared input; choose one explicitly with --audio.")
    return next(iter(candidates)) if candidates else None


def load_inputs(input_root: Path, audio_path: Path | None = None) -> InputBundle:
    """Validate four ordered scenes and return only DreamModel's allowed inputs."""
    root = Path(input_root).resolve()
    storyboard = root / "storyboard"
    objects_dir = root / "objects"
    manifest_paths = (storyboard / "scenes.json", storyboard / "dream_scenes.json", objects_dir / "objects.json")
    metadata, stories, object_manifest = (_read_manifest(path) for path in manifest_paths)
    scene_meta = _scene_map(metadata, "act", "scenes.json")
    scene_stories = _scene_map(stories, "scene", "dream_scenes.json")
    scene_objects = _scene_map(object_manifest, "scene", "objects.json")
    if set(scene_meta) != set(scene_stories) or set(scene_meta) != set(scene_objects):
        raise ValueError("Scene IDs must match across scenes.json, dream_scenes.json and objects.json.")

    warnings: list[str] = []
    files: list[Path] = list(manifest_paths)
    scenes: list[SceneInput] = []
    used_object_paths: set[Path] = set()
    for scene_id, meta in scene_meta.items():
        prefix = f"scene {scene_id}"
        stage = meta.get("stage")
        if not isinstance(stage, str) or stage not in STAGES:
            raise ValueError(f"{prefix}: explicit upstream stage must be one of 기, 승, 전, 결; got {stage!r}.")
        title = _text(meta.get("title"), f"{prefix}.title")
        emotion = _text(meta.get("emotion"), f"{prefix}.emotion")
        intensity = _intensity(meta.get("intensity"), f"{prefix}.intensity")
        dream = scene_stories[scene_id]
        story = _text(dream.get("story"), f"{prefix}.story")
        upstream_emotion = dream.get("main_emotion")
        if upstream_emotion is not None:
            if not isinstance(upstream_emotion, dict):
                raise ValueError(f"{prefix}.main_emotion must contain label and intensity.")
            label = _text(upstream_emotion.get("label"), f"{prefix}.main_emotion.label")
            level = _intensity(upstream_emotion.get("intensity"), f"{prefix}.main_emotion.intensity")
            if label != emotion or not math.isclose(level, intensity, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(f"{prefix}: emotion/intensity conflict between scenes.json and dream_scenes.json.")
        background_files = meta.get("files")
        if not isinstance(background_files, dict):
            raise ValueError(f"{prefix}: files.background is required.")
        background = _asset_path(storyboard, background_files.get("background"), f"{prefix}.files.background")
        _validate_image(background, object_image=False, warnings=warnings)
        files.append(background)

        entries = scene_objects[scene_id].get("objects")
        names = dream.get("objects")
        if not isinstance(entries, list) or not entries or not isinstance(names, list) or len(entries) != len(names):
            raise ValueError(f"{prefix}: objects.json must have a nonempty object list matching dream_scenes.json.objects.")
        resolved_objects: list[ObjectInput] = []
        for index, (entry, story_name) in enumerate(zip(entries, names), start=1):
            if not isinstance(entry, dict) or type(entry.get("index")) is not int or entry["index"] != index:
                raise ValueError(f"{prefix}: object index must match its 1-based story order ({index}).")
            name = _text(entry.get("name_ko"), f"{prefix}.object[{index}].name_ko")
            if name != _text(story_name, f"{prefix}.story.objects[{index}]"):
                raise ValueError(f"{prefix}: object name/order conflict at index {index}.")
            path = _asset_path(objects_dir, entry.get("file"), f"{prefix}.object[{index}].file")
            if path in used_object_paths:
                raise ValueError(f"Object asset is referenced more than once: {path}")
            used_object_paths.add(path)
            _validate_image(path, object_image=True, warnings=warnings)
            files.append(path)
            resolved_objects.append(ObjectInput(scene_id, index, name, path))
        laws = dream.get('physics_laws', [])
        if not isinstance(laws, list) or any(not isinstance(law, str) or not law.strip() for law in laws):
            raise ValueError(f'{prefix}.physics_laws must be a list of nonempty strings.')
        scenes.append(SceneInput(scene_id, stage, title, emotion, intensity, story, background,
                                 tuple(resolved_objects), tuple(laws)))

    audio = _select_audio(root, tuple(zip(manifest_paths, (metadata, stories, object_manifest))), audio_path)
    if audio is not None:
        files.append(audio)
    else:
        warnings.append("No audio supplied under shared input; render will be silent and audio RMS will be zero.")
    return InputBundle(tuple(scenes), tuple(dict.fromkeys(files)), audio, tuple(warnings))
