"""Input and active-source fingerprints for reproducible render reports."""
import hashlib
from pathlib import Path
from ..config import MODEL_ROOT, REPO_ROOT

def readable_path(path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(REPO_ROOT).as_posix() if resolved.is_relative_to(REPO_ROOT) else resolved.as_posix()

def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_files():
    paths = [MODEL_ROOT/'main.py', MODEL_ROOT/'config.py', MODEL_ROOT/'requirements.txt']
    for folder, pattern in [('runtime','*.py'), ('configs','*.json')]:
        paths.extend(sorted((MODEL_ROOT/folder).glob(pattern)))
    return paths


def code_records(extra=()):
    return [{'path': str(p), 'sha256': file_digest(p)}
            for p in dict.fromkeys([*source_files(), *map(Path,extra)])]
