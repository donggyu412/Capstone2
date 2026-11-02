"""Object-only cellular automata renderer for Team 4.

The object input is a video on a black background. Each frame is treated as
the object's appearance; thresholding creates the support mask, and CA updates
are constrained to that mask. The background remains black for later
compositing with DreamModel's background output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np

import config as cfg


def find_sound() -> Path:
    supported = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
    tracks = sorted(p for p in cfg.SOUND_DIR.iterdir()
                    if p.is_file() and p.suffix.lower() in supported)
    if not tracks:
        raise FileNotFoundError(f"음악 파일을 찾지 못했습니다: {cfg.SOUND_DIR}")
    if len(tracks) > 1:
        print(f"[GridModel] 여러 음악 중 첫 파일 사용: {tracks[0].name}")
    return tracks[0]


def find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError("FFmpeg 또는 imageio-ffmpeg가 필요합니다.") from exc


EMOTION_MOTION = {
    # base, slow breathing, audio, peak, period, phase, peak-triggered rotation limit
    "기쁨": (1.008, 0.006, 0.007, 0.004, 15.0, 0.00, 4.0),
    "슬픔": (0.992, 0.004, 0.003, 0.002, 28.0, 0.35, 0.0),
    "분노": (1.002, 0.004, 0.006, 0.006, 12.0, 0.60, 16.0),
    "공포": (0.994, 0.003, 0.004, 0.007, 22.0, 0.20, 14.0),
    "놀람": (1.000, 0.003, 0.004, 0.009, 19.0, 0.75, 25.0),
    "혐오": (0.991, 0.003, 0.003, 0.003, 25.0, 0.50, 7.0),
    "중립": (1.000, 0.002, 0.002, 0.002, 30.0, 0.10, 0.0),
}
STILL_MOTION = (1.0, 0.0, 0.0, 0.0, 30.0, 0.0, 0.0)


def background_colour_profiles() -> list[tuple[float, float, float, float, float, float, float]] | None:
    """Build fallback motion profiles from four sampled background video frames."""
    supported = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    videos = sorted(p for p in cfg.BACKGROUND_DIR.iterdir()
                    if p.is_file() and p.suffix.lower() in supported)
    if len(videos) != 1:
        return None
    capture = cv2.VideoCapture(str(videos[0]))
    if not capture.isOpened():
        return None
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count < 4:
            return None
        profiles = []
        for fraction in (0.10, 0.35, 0.65, 0.90):
            capture.set(cv2.CAP_PROP_POS_FRAMES, min(frame_count - 1, int(frame_count * fraction)))
            ok, frame = capture.read()
            if not ok or frame is None:
                return None
            small = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
            blue, green, red = small.mean(axis=(0, 1))
            brightness = float(0.114 * blue + 0.587 * green + 0.299 * red)
            chroma = float(np.mean(small.max(axis=2) - small.min(axis=2)))
            contrast = float(np.std(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)))
            warmth = float(red - blue)
            # Bright, colourful plates breathe more openly; dark, high-contrast plates react sparsely.
            base = 0.994 + 0.012 * brightness
            breath = 0.001 + 0.003 * chroma
            audio = 0.0015 + 0.0035 * contrast
            peak = 0.001 + 0.003 * (1.0 - brightness)
            period = 17.0 + 14.0 * (1.0 - chroma)
            phase = (warmth + 1.0) * 0.25
            rotation = min(cfg.MAX_ROTATION_DEGREES, 8.0 * contrast)
            profiles.append((base, breath, audio, peak, period, phase, rotation))
        print(f"[GridModel] 배경 색·밝기 보조 프로필 준비 ({videos[0].name})")
        return profiles
    finally:
        capture.release()


def scene_motion_profiles() -> list[tuple[float, float, float, float, float, float, float]]:
    """Use emotions first, then background colour; remain still if neither is available."""
    colour_profiles = background_colour_profiles()
    if not cfg.SCENES_FILE.is_file():
        if colour_profiles is not None:
            return colour_profiles
        print(f"[GridModel] 감정·배경 정보를 읽지 못함: 크기 변화 없음")
        return [STILL_MOTION] * 4
    try:
        scenes = json.loads(cfg.SCENES_FILE.read_text(encoding="utf-8-sig")).get("scenes", [])
    except (OSError, json.JSONDecodeError) as exc:
        if colour_profiles is not None:
            print(f"[GridModel] scenes.json을 읽지 못함: 배경 색 기반 움직임 사용 ({exc})")
            return colour_profiles
        print(f"[GridModel] 감정·배경 정보를 읽지 못함: 크기 변화 없음 ({exc})")
        return [STILL_MOTION] * 4
    profiles = []
    for index in range(4):
        scene = scenes[index] if index < len(scenes) else {}
        emotion = scene.get("emotion", "중립") if isinstance(scene, dict) else "중립"
        intensity = float(scene.get("intensity", 0.5)) if isinstance(scene, dict) else 0.5
        fallback = colour_profiles[index] if colour_profiles is not None else STILL_MOTION
        if emotion not in EMOTION_MOTION:
            profiles.append(fallback)
            continue
        base, breath, audio, peak, period, phase, rotation = EMOTION_MOTION[emotion]
        # 감정 강도는 변화 폭만 부드럽게 조절한다. 기준 크기는 감정별 성격을 유지한다.
        amount = 0.65 + 0.35 * np.clip(intensity, 0.0, 1.0)
        profiles.append((base, breath * amount, audio * amount, peak * amount,
                         period, phase, rotation * amount))
    print("[GridModel] 감정 기반 움직임 사용")
    return profiles


def smooth_signal(values: np.ndarray, seconds: float, rate: float) -> np.ndarray:
    width = max(1, round(seconds * rate))
    if width == 1:
        return values
    kernel = np.full(width, 1.0 / width, dtype=np.float32)
    return np.convolve(np.pad(values, (width // 2, width - 1 - width // 2), mode="edge"),
                       kernel, mode="valid")


def beat_pulses(levels: np.ndarray, rate: float) -> tuple[np.ndarray, np.ndarray]:
    """Use sparse musical peaks, avoiding frame-by-frame size jitter."""
    local = smooth_signal(levels, 3.0, rate)
    accent = np.maximum(0.0, levels - local)
    threshold = float(np.percentile(accent, 98))
    minimum_gap = max(1, round(cfg.BEAT_MIN_GAP_SECONDS * rate))
    events: list[int] = []
    last = -minimum_gap
    for index in range(1, len(accent) - 1):
        if (accent[index] >= threshold and accent[index] >= accent[index - 1]
                and accent[index] > accent[index + 1] and index - last >= minimum_gap):
            events.append(index)
            last = index
    pulse = np.zeros_like(levels)
    signed_pulse = np.zeros_like(levels)
    decay = max(1, round(cfg.BEAT_DECAY_SECONDS * rate))
    attack = max(1, round(cfg.ROTATION_ATTACK_SECONDS * rate))
    directions = np.random.default_rng(cfg.RANDOM_SEED).choice((-1.0, 1.0), size=len(events))
    for event, direction in zip(events, directions):
        end = min(len(pulse), event + decay * 3)
        elapsed = np.arange(end - event)
        envelope = np.minimum(1.0, elapsed / attack) * np.exp(-np.maximum(0, elapsed - attack) / decay)
        pulse[event:end] = np.maximum(pulse[event:end], envelope)
        signed_pulse[event:end] = np.where(
            envelope > np.abs(signed_pulse[event:end]), direction * envelope, signed_pulse[event:end]
        )
    return pulse, signed_pulse


def sound_motion(sound_path: Path, fps: float, frame_count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Make slow emotion-led motion with gentle sound energy and sparse peaks."""
    sample_rate = 4000
    window = sample_rate // 20
    command = [find_ffmpeg(), "-v", "error", "-i", str(sound_path),
               "-t", str(cfg.MAX_DURATION_SECONDS), "-ac", "1", "-ar", str(sample_rate),
               "-f", "s16le", "-"]
    decoded = subprocess.run(command, capture_output=True, check=True).stdout
    samples = np.frombuffer(decoded, dtype="<i2").astype(np.float32) / 32768.0
    if samples.size == 0:
        raise RuntimeError(f"음악을 읽지 못했습니다: {sound_path}")
    padded = np.pad(samples, (0, (-samples.size) % window))
    rms = np.sqrt(np.mean(padded.reshape(-1, window) ** 2, axis=1))
    low, high = np.percentile(rms, [10, 95])
    strength = np.clip((rms - low) / max(high - low, 1e-5), 0.0, 1.0)
    slow_strength = smooth_signal(strength, cfg.AUDIO_SMOOTH_SECONDS, 20.0)
    peaks, signed_peaks = beat_pulses(strength, 20.0)
    times = np.arange(frame_count, dtype=np.float32) / fps
    energy = np.interp(times, np.arange(len(slow_strength)) / 20.0, slow_strength,
                       left=float(slow_strength[0]), right=float(slow_strength[-1]))
    beat = np.interp(times, np.arange(len(peaks)) / 20.0, peaks,
                     left=float(peaks[0]), right=float(peaks[-1]))
    signed_beat = np.interp(times, np.arange(len(signed_peaks)) / 20.0, signed_peaks,
                            left=float(signed_peaks[0]), right=float(signed_peaks[-1]))
    profiles = scene_motion_profiles()
    scales = np.empty(frame_count, dtype=np.float32)
    rotations = np.empty(frame_count, dtype=np.float32)
    for index, time in enumerate(times):
        scene_position = min(3, int(time // 75.0))
        progress = (time % 75.0) / 75.0
        profile = np.array(profiles[scene_position], dtype=np.float32)
        # Blend the ending scene profile into the next one over four seconds.
        if scene_position < 3 and time % 75.0 >= 75.0 - cfg.SCENE_TRANSITION_SECONDS:
            blend = (time % 75.0 - (75.0 - cfg.SCENE_TRANSITION_SECONDS)) / cfg.SCENE_TRANSITION_SECONDS
            profile = profile * (1.0 - blend) + np.array(profiles[scene_position + 1]) * blend
        base, breath, audio, peak, period, phase, rotation_limit = profile
        slow_breath = breath * np.sin(2.0 * np.pi * (progress * 75.0 / period + phase))
        scales[index] = base + slow_breath + audio * energy[index] + peak * beat[index]
        rotations[index] = rotation_limit * signed_beat[index]
    return (np.clip(scales, cfg.OBJECT_MIN_SCALE, cfg.OBJECT_MAX_SCALE),
            np.clip(rotations, -cfg.MAX_ROTATION_DEGREES, cfg.MAX_ROTATION_DEGREES),
            energy)


def source_frame_indices(energy: np.ndarray, fps: float, frame_count: int) -> np.ndarray:
    """Vary source playback speed while consuming each 75-second scene in 75 seconds."""
    indices = np.zeros(frame_count, dtype=np.int32)
    scene_frames = max(1, round(cfg.SCENE_DURATION_SECONDS * fps))
    for start in range(0, frame_count, scene_frames):
        end = min(frame_count, start + scene_frames)
        count = end - start
        if count == 1:
            indices[start] = start
            continue
        # Loud passages move through the source more quickly, quiet passages more slowly.
        local_energy = energy[start:end]
        relative_energy = local_energy - float(local_energy.mean())
        speeds = 1.0 + cfg.PLAYBACK_SPEED_RESPONSE * relative_energy
        speeds = np.clip(speeds, cfg.PLAYBACK_SPEED_MIN, cfg.PLAYBACK_SPEED_MAX)
        distance = np.concatenate(([0.0], np.cumsum(speeds[:-1], dtype=np.float64)))
        # Re-scale cumulative travel so this source scene begins and ends with this output scene.
        distance *= (count - 1) / max(float(distance[-1]), 1e-6)
        indices[start:end] = start + np.rint(distance).astype(np.int32)
    return indices


def intro_opacity(frame_index: int, fps: float) -> float:
    """Hold black, then reveal the object with a smooth three-second fade."""
    seconds = frame_index / fps
    if seconds <= cfg.INTRO_BLACKOUT_SECONDS:
        return 0.0
    progress = np.clip((seconds - cfg.INTRO_BLACKOUT_SECONDS) / cfg.INTRO_FADE_IN_SECONDS, 0.0, 1.0)
    return float(progress * progress * (3.0 - 2.0 * progress))


def resize_object(result: np.ndarray, scale: float, angle: float = 0.0) -> np.ndarray:
    """Scale and, only on a sparse peak, rotate the object around its own centre."""
    points = cv2.findNonZero(cv2.cvtColor(result, cv2.COLOR_BGR2GRAY))
    if points is None:
        return result
    x, y, width, height = cv2.boundingRect(points)
    crop = result[y:y + height, x:x + width]
    scaled_width = max(1, round(width * scale))
    scaled_height = max(1, round(height * scale))
    scaled = cv2.resize(crop, (scaled_width, scaled_height), interpolation=cv2.INTER_NEAREST)
    padding = max(2, round(max(scaled_width, scaled_height) * 0.25))
    padded = cv2.copyMakeBorder(scaled, padding, padding, padding, padding,
                                cv2.BORDER_CONSTANT, value=(0, 0, 0))
    centre = ((padded.shape[1] - 1) / 2, (padded.shape[0] - 1) / 2)
    matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
    transformed = cv2.warpAffine(padded, matrix, padded.shape[1::-1],
                                 flags=cv2.INTER_NEAREST, borderValue=(0, 0, 0))
    left = round(x + width / 2 - transformed.shape[1] / 2)
    top = round(y + height / 2 - transformed.shape[0] / 2)
    right, bottom = left + transformed.shape[1], top + transformed.shape[0]
    canvas = np.zeros_like(result)
    dst_x0, dst_y0 = max(0, left), max(0, top)
    dst_x1, dst_y1 = min(result.shape[1], right), min(result.shape[0], bottom)
    if dst_x1 > dst_x0 and dst_y1 > dst_y0:
        canvas[dst_y0:dst_y1, dst_x0:dst_x1] = transformed[
            dst_y0 - top:dst_y1 - top, dst_x0 - left:dst_x1 - left]
    return canvas


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


def render_object_video(input_path: Path, output_path: Path, sound_path: Path) -> None:
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"오브제 영상을 열 수 없습니다: {input_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or cfg.OUTPUT_FPS
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    max_frames = min(count, round(cfg.MAX_DURATION_SECONDS * fps)) if count > 0 else round(cfg.MAX_DURATION_SECONDS * fps)
    scales, rotations, energy = sound_motion(sound_path, fps, max_frames)
    source_indices = source_frame_indices(energy, fps, max_frames)
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
    source_index = -1
    source_frame: np.ndarray | None = None
    try:
        while True:
            if frame_index >= max_frames:
                break
            target_source_index = int(source_indices[frame_index])
            while source_index < target_source_index:
                ok, source_frame = capture.read()
                if not ok:
                    raise RuntimeError(
                        f"입력 오브제 영상의 프레임을 읽지 못했습니다: {target_source_index}"
                    )
                source_index += 1
            if source_frame is None:
                break
            result, state = ca_object_frame(source_frame, state, rng)
            result = resize_object(result, float(scales[frame_index]), float(rotations[frame_index]))
            opacity = intro_opacity(frame_index, fps)
            if opacity < 1.0:
                result = (result.astype(np.float32) * opacity).astype(np.uint8)
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


def make_preview(video_path: Path, sound_path: Path) -> Path:
    preview = cfg.OUT_DIR / cfg.OUTPUT_PREVIEW_NAME
    subprocess.run([find_ffmpeg(), "-y", "-v", "error", "-i", str(video_path),
                    "-i", str(sound_path), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-shortest", "-t",
                    str(cfg.MAX_DURATION_SECONDS), str(preview)], check=True)
    return preview


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the GridModel object layer")
    parser.add_argument("--preview", action="store_true",
                        help="Also save a music-backed object-only review video")
    args = parser.parse_args()
    source = find_object_video()
    sound = find_sound()
    target = cfg.OUT_DIR / cfg.OUTPUT_OBJECT_NAME
    print(f"[GridModel] object input: {source}")
    print(f"[GridModel] sound input: {sound}")
    print(f"[GridModel] output: {target}")
    render_object_video(source, target, sound)
    if args.preview:
        print(f"[GridModel] preview with sound: {make_preview(target, sound)}")


if __name__ == "__main__":
    main()
