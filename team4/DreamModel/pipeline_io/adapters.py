"""Read the inputs delivered to DreamModel without changing them.

Team 3 manifest interpretation and object transparency checks remain TODO.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from team4.DreamModel.config import MODEL_INPUT_ROOT

STORY_SEARCH_ROOTS = (MODEL_INPUT_ROOT,)
ASSET_SEARCH_ROOTS = (MODEL_INPUT_ROOT,)
OBJECT_DIRECTORY_NAMES = frozenset({"objects", "object", "object_images"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
SKIPPED_DIRECTORY_NAMES = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules"}
)
SCENE_FOLDER_PATTERN = re.compile(r"scene[_-]?0?([1-4])", re.IGNORECASE)
BACKGROUND_NAMES = {f"scene_{index:02d}.png": index for index in range(1, 5)}


@dataclass
class StoryInput:
    """Raw scene positions and nonfatal input diagnostics."""

    path: Path | None = None
    scenes: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AssetInventory:
    """Existing assets only; shared objects have no inferred scene ownership."""

    backgrounds: dict[int, Path] = field(default_factory=dict)
    objects: dict[int, list[Path]] = field(default_factory=dict)
    shared_objects: list[Path] = field(default_factory=list)
    manifests: list[Path] = field(default_factory=list)
    object_directories: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def display_path(path: Path | None, repo_root: Path) -> str | None:
    """Use portable repository-relative paths, or an explicit external path."""
    if path is None:
        return None
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _scan(
    repo_root: Path, roots: tuple[str, ...], warnings: list[str]
) -> tuple[list[Path], list[Path]]:
    """Walk only candidate roots, in priority order; never follow symlinks."""
    files: list[Path] = []
    directories: list[Path] = []
    visited: set[Path] = set()

    def report(error: OSError) -> None:
        warnings.append(f"Cannot inspect an input directory: {error}")

    for relative_root in roots:
        root = repo_root / relative_root
        try:
            if root.is_symlink() or root.is_junction() or not root.is_dir():
                continue
            try:
                root.resolve().relative_to(repo_root.resolve())
            except ValueError:
                warnings.append(f"Skipped input directory outside repository: {root}")
                continue
            for current, child_dirs, filenames in os.walk(
                root, followlinks=False, onerror=report
            ):
                directory = Path(current)
                if directory in visited:
                    child_dirs[:] = []
                    continue
                visited.add(directory)
                directories.append(directory)
                child_dirs[:] = sorted(
                    name
                    for name in child_dirs
                    if name not in SKIPPED_DIRECTORY_NAMES
                    and not (directory / name).is_symlink()
                    and not (directory / name).is_junction()
                )
                for filename in sorted(filenames):
                    path = directory / filename
                    if not path.is_symlink() and path.is_file():
                        files.append(path)
        except (OSError, ValueError, RuntimeError) as error:
            warnings.append(f"Cannot inspect input directory {root}: {error}")
    return files, directories


def _story_candidates(repo_root: Path, warnings: list[str]) -> list[Path]:
    files, _ = _scan(repo_root, STORY_SEARCH_ROOTS, warnings)
    return [path for path in files if path.name == "dream_scenes.json"]


def _read_scenes(path: Path, warnings: list[str]) -> list[object] | None:
    try:
        with path.open("r", encoding="utf-8-sig") as source:
            payload = json.load(source)
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        warnings.append(f"Cannot read story JSON {path.as_posix()}: {error}")
        return None
    scenes = payload.get("scenes") if isinstance(payload, dict) else payload
    if not isinstance(scenes, list):
        warnings.append(
            f"Story JSON {path.as_posix()} must contain a scenes list "
            "or be a JSON list."
        )
        return None
    return scenes


def load_story(repo_root: Path, explicit_path: Path | None = None) -> StoryInput:
    """Read the first valid candidate and preserve its first four scene slots.

    Relative explicit paths use the current working directory. An explicit path is
    authoritative and never silently falls back to a different story file.
    """
    result = StoryInput()
    if explicit_path is not None:
        candidates = [explicit_path]
    else:
        candidates = _story_candidates(repo_root, result.warnings)
    if not candidates:
        result.warnings.append(
            f"No dream_scenes.json found in {MODEL_INPUT_ROOT}. "
            "Add the delivered story there or provide an explicit input path."
        )
        return result

    for candidate in candidates:
        scenes = _read_scenes(candidate, result.warnings)
        if scenes is None:
            continue
        result.path = candidate
        if len(candidates) > 1:
            result.warnings.append(
                f"Selected {display_path(candidate, repo_root)} from "
                f"{len(candidates)} story candidates; other candidates were not selected."
            )
        if len(scenes) != 4:
            result.warnings.append(
                f"Story contains {len(scenes)} scenes; expected 4. "
                "Only existing first four slots are planned."
            )
        for index, scene in enumerate(scenes[:4], start=1):
            if isinstance(scene, dict):
                result.scenes.append(scene)
            else:
                result.scenes.append({})
                result.warnings.append(
                    f"Scene slot {index} is not an object; using temporary defaults."
                )
        return result

    result.warnings.append("No usable story JSON found; no scene plan was invented.")
    return result


def _object_scene(path: Path, repo_root: Path) -> int | None:
    """Recognize only explicitly named scene folders, never list position."""
    for part in reversed(path.relative_to(repo_root).parent.parts):
        match = SCENE_FOLDER_PATTERN.fullmatch(part)
        if match:
            return int(match.group(1))
    return None


def discover_assets(repo_root: Path) -> AssetInventory:
    """Find candidate image paths; scenes.json is discovered but not parsed.

    Root priority and sorted traversal break background-name ties. Only images
    inside objects/object/object_images folders are object candidates. Scene
    folders such as scene_01 or scene-1 assign objects explicitly; otherwise
    objects remain shared and must not be copied into every scene's plan.
    """
    result = AssetInventory()
    files, directories = _scan(repo_root, ASSET_SEARCH_ROOTS, result.warnings)
    result.object_directories = [
        path for path in directories if path.name.lower() in OBJECT_DIRECTORY_NAMES
    ]
    duplicate_backgrounds: set[int] = set()
    for path in files:
        if path.name == "scenes.json":
            result.manifests.append(path)
        parts = path.relative_to(repo_root).parent.parts
        is_object = any(part.lower() in OBJECT_DIRECTORY_NAMES for part in parts)
        if is_object and path.suffix.lower() in IMAGE_EXTENSIONS:
            scene = _object_scene(path, repo_root)
            if scene is None:
                result.shared_objects.append(path)
            else:
                result.objects.setdefault(scene, []).append(path)
        elif not is_object and path.name in BACKGROUND_NAMES:
            scene = BACKGROUND_NAMES[path.name]
            if scene in result.backgrounds:
                duplicate_backgrounds.add(scene)
            else:
                result.backgrounds[scene] = path

    if duplicate_backgrounds:
        result.warnings.append(
            "Multiple background candidates for scenes "
            f"{sorted(duplicate_backgrounds)}; used search-root and path priority."
        )
    missing = [scene for scene in range(1, 5) if scene not in result.backgrounds]
    if missing:
        result.warnings.append(f"No background image found for scene slots {missing}.")
    if not result.object_directories:
        result.warnings.append("No candidate object image directory found.")
    if not result.manifests:
        result.warnings.append("No scenes.json manifest found; its contract is pending.")
    return result
