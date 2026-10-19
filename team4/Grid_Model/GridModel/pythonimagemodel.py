"""Object-only cellular automata renderer for Team 4.

The object input is a video on a black background. Each frame is treated as
the object's appearance; thresholding creates the support mask, and CA updates
are constrained to that mask. The background remains black for later
compositing with DreamModel's background output.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import config as cfg


def find_object_video() -> Path:
    """Find the configured MP4, falling back to the first MP4 in input/object."""
    if cfg.OBJECT_VIDEO.exists():
        return cfg.OBJECT_VIDEO
    candidates = sorted(cfg.OBJECT_INPUT_DIR.glob("*.mp4"))
    if not candidates:
        raise FileNotFoundError(
            f"오브제 입력 MP4를 찾지 못했습니다: {cfg.OBJECT_INPUT_DIR}"
        )
    return candidates[0]


def ca_object_frame(frame_bgr: np.ndarray, state: np.ndarray,
                    rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Apply a local, mask-bounded cellular automaton to one object frame."""
    h, w = cfg.CA_HEIGHT, cfg.CA_WIDTH
    small = cv2.resize(frame_bgr, (w, h), interpolation=cv2.INTER_AREA)
    # The supplied MP4 uses black as its empty/background color. Use luminance
    # with a small floor so compression noise does not become object material.
    luminance = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    support = luminance >= cfg.OBJECT_MASK_THRESHOLD
    if not np.any(support):
        return np.zeros((h, w, 3), dtype=np.uint8), np.zeros((h, w), dtype=np.float32)

    alive = support & (state > cfg.OBJECT_ALIVE_THRESHOLD)
    # Start a fresh object's automaton from a few cells when the source
    # silhouette first appears (including after a black transition).
    if not np.any(alive):
        ys, xs = np.nonzero(support)
        seed_count = min(cfg.CA_INITIAL_SEEDS, len(xs))
        if seed_count:
            chosen = rng.choice(len(xs), size=seed_count, replace=False)
            state[ys[chosen], xs[chosen]] = rng.uniform(
                cfg.CA_BIRTH_MIN_STATE, 1.0, size=seed_count
            )
            alive = support & (state > cfg.OBJECT_ALIVE_THRESHOLD)
    neighbor_count = cv2.filter2D(
        alive.astype(np.uint8), -1,
        np.ones((3, 3), dtype=np.uint8), borderType=cv2.BORDER_CONSTANT,
    ) - alive.astype(np.uint8)

    # Generative object CA: surviving cells persist with a jittering state;
    # nearby empty cells can ignite only inside the current object silhouette.
    birth = support & ~alive & (neighbor_count >= cfg.CA_BIRTH_MIN_NEIGHBORS)
    death = alive & ((neighbor_count <= cfg.CA_DEATH_MAX_NEIGHBORS) |
                     (rng.random((h, w)) < cfg.CA_CELL_FLICKER))
    state[death] *= cfg.CA_DEATH_RETAIN
    state[birth] = rng.uniform(cfg.CA_BIRTH_MIN_STATE, 1.0, size=int(birth.sum()))
    state[alive & ~death] = np.clip(
        state[alive & ~death] + rng.normal(0.0, cfg.CA_STATE_JITTER,
                                           size=int((alive & ~death).sum())), 0.0, 1.0
    )
    # The source's silhouette remains the hard boundary; CA changes its
    # cellular texture and local visibility without touching empty pixels.
    state[~support] = 0.0
    state[birth] = np.maximum(state[birth], cfg.CA_MIN_VISIBLE_STATE)

    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.float32)
    modulation = cfg.CA_BASE_BRIGHTNESS + state[..., None] * cfg.CA_STATE_BRIGHTNESS
    modulation *= rng.uniform(1.0 - cfg.CA_COLOR_JITTER,
                              1.0 + cfg.CA_COLOR_JITTER, size=(h, w, 1))
    rendered = np.clip(rgb * modulation, 0, 255).astype(np.uint8)
    rendered[~support] = 0
    return cv2.cvtColor(rendered, cv2.COLOR_RGB2BGR), state


def render_object_video(input_path: Path, output_path: Path) -> None:
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"오브제 영상을 열 수 없습니다: {input_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or cfg.OUTPUT_FPS
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps,
        (cfg.OUTPUT_WIDTH or width, cfg.OUTPUT_HEIGHT or height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"출력 영상을 만들 수 없습니다: {output_path}")

    rng = np.random.default_rng(cfg.RANDOM_SEED)
    state = np.zeros((cfg.CA_HEIGHT, cfg.CA_WIDTH), dtype=np.float32)
    # Video starts/stops with black frames; seed new object appearances from
    # the source silhouette so the CA has material to evolve immediately.
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            result, state = ca_object_frame(frame, state, rng)
            output_size = (cfg.OUTPUT_WIDTH or width, cfg.OUTPUT_HEIGHT or height)
            if result.shape[1::-1] != output_size:
                result = cv2.resize(result, output_size, interpolation=cv2.INTER_NEAREST)
            writer.write(result)
            frame_index += 1
            if frame_index % max(1, int(fps * 10)) == 0:
                print(f"[GridModel] {frame_index}/{count or '?'} frames")
    finally:
        capture.release()
        writer.release()
    if frame_index == 0:
        raise RuntimeError(f"입력 영상에 읽을 수 있는 프레임이 없습니다: {input_path}")
    print(f"[GridModel] object-only video saved: {output_path} ({frame_index} frames)")


def main() -> None:
    source = find_object_video()
    target = cfg.OUT_DIR / cfg.OUTPUT_OBJECT_NAME
    print(f"[GridModel] object input: {source}")
    print(f"[GridModel] output: {target}")
    render_object_video(source, target)


if __name__ == "__main__":
    main()
