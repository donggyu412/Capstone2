# python_image_model_v1_3.py
from __future__ import annotations

import math
import re
import json
import unicodedata
import shutil
import subprocess
from pathlib import Path

import cv2
import librosa
import numpy as np
from tqdm import tqdm

import config as cfg


def clamp01(x):
    return np.clip(x, 0.0, 1.0)


def smoothstep01(t):
    t = float(np.clip(t, 0.0, 1.0))
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def natural_key(path: Path):
    return [int(s) if s.isdigit() else s.lower() for s in re.split(r"(\d+)", path.stem)]


def convert_60fps_chance_to_step(chance_at_60fps: float, step_dt: float) -> float:
    chance = float(np.clip(chance_at_60fps, 0.0, 1.0))
    return 1.0 - math.pow(1.0 - chance, step_dt * 60.0)


DIRECTION_X = np.array([-1, 0, 1, -1, 1, -1, 0, 1], dtype=np.int32)
DIRECTION_Y = np.array([-1, -1, -1, 0, 0, 1, 1, 1], dtype=np.int32)


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", str(value)).strip()


def find_audio_file() -> Path | None:
    """
    새 구조에서는 사운드 위치를 강제하지 않습니다.
    input 폴더 아래를 재귀적으로 검색해 첫 오디오 파일을 사용합니다.
    """
    exts = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}

    if not cfg.INPUT_DIR.exists():
        return None

    files = sorted(
        [
            p for p in cfg.INPUT_DIR.rglob("*")
            if p.is_file() and p.suffix.lower() in exts
        ],
        key=lambda p: normalize_text(str(p.relative_to(cfg.INPUT_DIR))),
    )
    return files[0] if files else None


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"필수 JSON 파일을 찾지 못했습니다: {path}")

    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _find_object_file(scene_dir: Path, order: int, object_name: str) -> Path:
    """
    README 규칙:
      scene_0N/obj_<순번>_<오브제이름>.png

    실제 파일명은 Unicode NFC/NFD 차이가 있을 수 있으므로
    정규화해서 비교합니다.
    """
    allowed_exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

    if not scene_dir.exists():
        raise FileNotFoundError(f"오브제 scene 폴더가 없습니다: {scene_dir}")

    candidates = [
        p for p in scene_dir.iterdir()
        if p.is_file() and p.suffix.lower() in allowed_exts
    ]

    prefix = f"obj_{order}_"
    prefix_matches = [
        p for p in candidates
        if normalize_text(p.stem).startswith(prefix)
    ]

    if len(prefix_matches) == 1:
        return prefix_matches[0]

    expected_stem = normalize_text(
        f"obj_{order}_{object_name.replace(' ', '_')}"
    )

    exact = [
        p for p in candidates
        if normalize_text(p.stem) == expected_stem
    ]

    if len(exact) == 1:
        return exact[0]

    existing = ", ".join(sorted(p.name for p in candidates)) or "없음"

    if not prefix_matches:
        raise FileNotFoundError(
            f"scene_{scene_dir.name[-2:]}의 {order}번 오브제를 찾지 못했습니다.\n"
            f"JSON 오브제 이름: {object_name}\n"
            f"예상 예시: {expected_stem}.png\n"
            f"현재 파일: {existing}"
        )

    raise RuntimeError(
        f"{scene_dir}에서 obj_{order}_ 로 시작하는 파일이 여러 개입니다: "
        + ", ".join(p.name for p in prefix_matches)
    )


def load_scene_manifest():
    """
    scenes.json:
      - 배경 파일과 장면 메타데이터

    dream_scenes.json:
      - scene 번호
      - scene별 story
      - scene별 objects 순서

    두 JSON을 합쳐 GridModel이 사용하는 단일 manifest를 만듭니다.
    """
    scenes_data = load_json(cfg.SCENES_JSON)
    dream_data = load_json(cfg.DREAM_SCENES_JSON)

    scene_meta_list = scenes_data.get("scenes", [])
    dream_list = dream_data.get("scenes", [])

    if not scene_meta_list:
        raise ValueError(f"{cfg.SCENES_JSON.name}에 scenes 배열이 없습니다.")
    if not dream_list:
        raise ValueError(f"{cfg.DREAM_SCENES_JSON.name}에 scenes 배열이 없습니다.")

    dream_by_scene = {
        int(item["scene"]): item
        for item in dream_list
        if "scene" in item
    }

    manifest = []

    for index, meta in enumerate(scene_meta_list, start=1):
        scene_number = int(meta.get("act", index))

        dream = dream_by_scene.get(scene_number)
        if dream is None:
            raise ValueError(
                f"dream_scenes.json에서 scene {scene_number}을 찾지 못했습니다."
            )

        background_name = (
            meta.get("files", {}).get("background")
            or f"scene_{scene_number:02d}.png"
        )
        background_path = cfg.STORYBOARD_DIR / background_name

        if not background_path.exists():
            raise FileNotFoundError(
                f"scene {scene_number} 배경 파일을 찾지 못했습니다: {background_path}"
            )

        object_names = list(dream.get("objects", []))
        scene_object_dir = cfg.OBJECTS_DIR / f"scene_{scene_number:02d}"

        object_paths = []
        for order, object_name in enumerate(object_names, start=1):
            object_paths.append(
                _find_object_file(
                    scene_object_dir,
                    order,
                    normalize_text(object_name),
                )
            )

        manifest.append(
            {
                "scene": scene_number,
                "stage": meta.get("stage", ""),
                "title": meta.get("title", ""),
                "emotion": meta.get("emotion", ""),
                "intensity": float(meta.get("intensity", 1.0)),
                "background_path": background_path,
                "story": str(dream.get("story", "")),
                "object_names": object_names,
                "object_paths": object_paths,
            }
        )

    print("[Scene manifest]")
    for item in manifest:
        print(
            f"  scene_{item['scene']:02d} | "
            f"background={item['background_path'].name} | "
            f"objects={len(item['object_paths'])} | "
            f"title={item['title']}"
        )
        for i, (name, path) in enumerate(
            zip(item["object_names"], item["object_paths"]),
            start=1,
        ):
            print(f"    obj_{i}: {name} -> {path.name}")

    return manifest


def load_image_paths(scene_manifest):
    return [item["background_path"] for item in scene_manifest]


def read_target_image(path: Path, grid_w: int, grid_h: int) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"이미지를 읽을 수 없습니다: {path}")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return cv2.resize(img, (grid_w, grid_h), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0


def read_object_image(path: Path):
    """
    오브제 이미지를 RGBA 형식으로 읽습니다.
    PNG 알파가 있으면 그대로 사용하고,
    없으면 완전 불투명(알파 1.0)으로 처리합니다.
    """
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"오브제 이미지를 읽을 수 없습니다: {path}")

    if img.ndim == 2:
        rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB).astype(np.float32) / 255.0
        alpha = np.ones((img.shape[0], img.shape[1], 1), dtype=np.float32)
        return np.concatenate([rgb, alpha], axis=2)

    if img.shape[2] == 4:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA).astype(np.float32) / 255.0
        return rgba

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    alpha = np.ones((img.shape[0], img.shape[1], 1), dtype=np.float32)
    return np.concatenate([rgb, alpha], axis=2)


DEFAULT_STORY = {
    "spread": 1.0,
    "blend": 1.0,
    "reveal": 1.0,
    "brightness": 1.0,
    "saturation": 1.0,
    "fade": 1.0,
    "noise": 0.0,
}


def contains_any(text: str, keywords) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


def story_values_for_sentence(sentence: str):
    p = dict(DEFAULT_STORY)
    detected = []

    if contains_any(sentence, ["어둠", "어두운", "어두워", "어둡", "검은", "검게", "암흑"]):
        p["brightness"] = 0.60
        p["saturation"] = 0.60
        p["reveal"] = 0.50
        detected.append("어둠")

    if contains_any(sentence, ["빛", "밝아", "밝은", "밝게", "환하게", "빛난", "빛나"]):
        p["brightness"] = 1.25
        p["saturation"] = 1.15
        p["reveal"] = 1.30
        detected.append("빛")

    if contains_any(sentence, ["흐릿", "희미", "흐려", "흐린", "뿌연", "모호"]):
        p["blend"] = 1.70
        p["reveal"] = 0.40
        p["saturation"] = 0.75
        detected.append("흐릿")

    if contains_any(sentence, ["선명", "뚜렷", "분명", "드러난", "드러내", "드러나"]):
        p["reveal"] = 1.50
        p["brightness"] = 1.10
        p["blend"] = 0.60
        detected.append("선명")

    if contains_any(sentence, ["번진", "번지", "퍼진", "퍼지", "퍼져", "확산", "스며"]):
        p["spread"] = 2.00
        p["blend"] = 1.40
        detected.append("번짐")

    if contains_any(sentence, ["흔들", "떨리", "떨린", "진동"]):
        p["noise"] = 0.80
        p["blend"] = 1.20
        detected.append("흔들림")

    if contains_any(sentence, ["왜곡", "뒤틀", "일그러", "비틀"]):
        p["noise"] = 1.50
        p["blend"] = 1.50
        detected.append("왜곡")

    if contains_any(sentence, ["사라", "소멸", "없어", "지워", "희미해진"]):
        p["fade"] = 0.55
        p["saturation"] = 0.45
        p["reveal"] = 0.30
        detected.append("사라짐")

    if contains_any(sentence, ["나타", "등장", "생겨", "생성", "형성", "보이기 시작"]):
        p["spread"] = 1.40
        p["reveal"] = 1.40
        detected.append("나타남")

    if contains_any(sentence, ["재구성", "변한다", "변화", "바뀐다", "바뀌", "재생성"]):
        p["spread"] = 1.80
        p["blend"] = 1.30
        detected.append("재구성")

    return p, detected


class StoryController:
    """
    dream_scenes.json의 story를 scene 단위로 사용합니다.

    scene마다 문장 개수가 다르기 때문에, 각 scene의 모든 문장을
    IMAGE_CHANGE_INTERVAL(75초) 안에 균등 배분합니다.
    """

    def __init__(self, scene_manifest):
        self.scene_data = []

        for scene in scene_manifest:
            text = str(scene.get("story", ""))
            text = text.replace("\r\n", "\n").replace("\r", "\n")

            # 문단 경계도 유지하면서 문장 단위로 분리
            parts = re.split(r"[.!?。]+|\n+", text)
            sentences = [p.strip() for p in parts if p.strip()]

            if not sentences:
                sentences = [""]

            targets = []
            detected = []

            for sentence in sentences:
                values, words = story_values_for_sentence(sentence)
                targets.append(values)
                detected.append(words)

            self.scene_data.append(
                {
                    "sentences": sentences,
                    "targets": targets,
                    "detected": detected,
                }
            )

    def state_at(self, scene_index: int, scene_local_time: float):
        if not cfg.USE_STORY_CONTROL:
            return "", dict(DEFAULT_STORY), []

        if not self.scene_data:
            return "", dict(DEFAULT_STORY), []

        scene_index = int(np.clip(scene_index, 0, len(self.scene_data) - 1))
        data = self.scene_data[scene_index]

        sentences = data["sentences"]
        targets = data["targets"]
        detected = data["detected"]

        count = max(1, len(sentences))

        if cfg.STORY_FIT_TO_SCENE:
            sentence_duration = cfg.IMAGE_CHANGE_INTERVAL / count
        else:
            sentence_duration = max(0.1, cfg.IMAGE_CHANGE_INTERVAL / count)

        index = min(
            int(scene_local_time // max(sentence_duration, 1e-6)),
            count - 1,
        )

        sentence_start = index * sentence_duration
        phase = max(0.0, scene_local_time - sentence_start)

        current = targets[index]
        previous = DEFAULT_STORY if index == 0 else targets[index - 1]

        blend_duration = min(
            cfg.STORY_TRANSITION_DURATION,
            sentence_duration * 0.45,
        )

        if blend_duration > 0.0 and phase < blend_duration:
            u = smoothstep01(phase / blend_duration)
            values = {
                k: float(lerp(previous[k], current[k], u))
                for k in DEFAULT_STORY
            }
        else:
            values = dict(current)

        return sentences[index], values, detected[index]


def blackman_harris_window(n: int):
    if n <= 1:
        return np.ones(n, dtype=np.float32)
    x = np.arange(n, dtype=np.float32)
    phase = 2.0 * np.pi * x / (n - 1)
    a0, a1, a2, a3 = 0.35875, 0.48829, 0.14128, 0.01168
    return (a0 - a1 * np.cos(phase) + a2 * np.cos(2.0 * phase) - a3 * np.cos(3.0 * phase)).astype(np.float32)


class AudioAnalyzer:
    def __init__(self, audio_path: Path | None):
        self.available = audio_path is not None and audio_path.exists()
        self.current_amplitude = 0.0
        self.window = blackman_harris_window(cfg.FFT_SIZE)

        if not self.available:
            self.y = np.zeros(1, dtype=np.float32)
            self.sr = 44100
            self.duration = 0.0
            return

        self.y, self.sr = librosa.load(str(audio_path), sr=None, mono=True)
        self.y = self.y.astype(np.float32)
        self.duration = len(self.y) / self.sr

    def raw_amplitude_at(self, t: float):
        if not self.available:
            return 0.0

        start = int(t * self.sr)
        end = start + cfg.FFT_SIZE
        if start >= len(self.y):
            return 0.0

        segment = np.zeros(cfg.FFT_SIZE, dtype=np.float32)
        available = self.y[start:min(end, len(self.y))]
        segment[:len(available)] = available

        spectrum = np.abs(np.fft.rfft(segment * self.window, n=cfg.FFT_SIZE)).astype(np.float32)
        spectrum = spectrum[:cfg.FFT_BINS]
        norm = max(float(np.sum(self.window)), 1e-6)
        spectrum = spectrum / norm

        raw = float(np.mean(spectrum))
        raw *= cfg.AMPLITUDE_MULTIPLIER
        raw *= cfg.FFT_COMPENSATION
        return raw

    def update(self, t: float, dt: float):
        raw = self.raw_amplitude_at(t)
        alpha = float(np.clip(dt * cfg.SMOOTHING_FACTOR, 0.0, 1.0))
        self.current_amplitude = float(lerp(self.current_amplitude, raw, alpha))
        return self.current_amplitude


class Perlin2D:
    def __init__(self, seed: int):
        rng = np.random.default_rng(seed)
        p = np.arange(256, dtype=np.int32)
        rng.shuffle(p)
        self.perm = np.concatenate([p, p])

    @staticmethod
    def fade(t):
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    @staticmethod
    def grad(hash_values, x, y):
        h = hash_values & 7
        u = np.where(h < 4, x, y)
        v = np.where(h < 4, y, x)
        a = np.where((h & 1) == 0, u, -u)
        b = np.where((h & 2) == 0, v, -v)
        return a + b

    def sample(self, x, y):
        xi = np.floor(x).astype(np.int32) & 255
        yi = np.floor(y).astype(np.int32) & 255
        xf = x - np.floor(x)
        yf = y - np.floor(y)
        u = self.fade(xf)
        v = self.fade(yf)

        aa = self.perm[self.perm[xi] + yi]
        ab = self.perm[self.perm[xi] + yi + 1]
        ba = self.perm[self.perm[xi + 1] + yi]
        bb = self.perm[self.perm[xi + 1] + yi + 1]

        x1 = lerp(self.grad(aa, xf, yf), self.grad(ba, xf - 1.0, yf), u)
        x2 = lerp(self.grad(ab, xf, yf - 1.0), self.grad(bb, xf - 1.0, yf - 1.0), u)
        return clamp01((lerp(x1, x2, v) + 1.0) * 0.5)


class DreamGridModel:
    def __init__(self, image_paths, story_controller, audio_analyzer):
        self.image_paths = image_paths
        self.story_controller = story_controller
        self.audio = audio_analyzer

        self.w = cfg.GRID_WIDTH
        self.h = cfg.GRID_HEIGHT
        self.total_cells = self.w * self.h

        self.targets = [read_target_image(p, self.w, self.h) for p in image_paths]

        self.current_image_index = 0
        self.current_colors = self.targets[0].copy()
        self.target_colors = self.targets[0].copy()

        self.has_new_color = np.ones((self.h, self.w), dtype=bool)
        self.active_cell_count = self.total_cells

        self.elapsed_time = 0.0
        self.reveal_amount = 0.0
        self.color_completion_progress = 1.0

        self.simulation_timer = 0.0
        self.noise_timer = 0.0

        self.rng = np.random.default_rng(cfg.RANDOM_SEED)
        self.noise_w = math.ceil(self.w / cfg.NOISE_RESOLUTION_DIVISOR)
        self.noise_h = math.ceil(self.h / cfg.NOISE_RESOLUTION_DIVISOR)
        self.noise_map = np.zeros((self.noise_h, self.noise_w), dtype=np.float32)
        self.perlin = Perlin2D(cfg.RANDOM_SEED + 917)

        self.story_sentence = ""
        self.story_detected = []
        self.story = dict(DEFAULT_STORY)

        self.last_rule_debug = {
            "audio01": 0.0,
            "radius": 1,
            "attempts": cfg.BASE_GROWTH_ATTEMPTS,
            "catchup": 1.0,
            "ambientChance": 0.0,
            "ambientActive": 0,
        }
        self.update_cached_noise_map(0.0)

    @property
    def spread_progress(self):
        return self.active_cell_count / max(1, self.total_cells)

    @property
    def visual_completion_progress(self):
        return self.color_completion_progress

    def update_cached_noise_map(self, global_time: float):
        t = global_time * cfg.SPREAD_NOISE_SPEED
        scale = cfg.SPREAD_NOISE_SCALE * cfg.NOISE_RESOLUTION_DIVISOR

        yy, xx = np.mgrid[0:self.noise_h, 0:self.noise_w].astype(np.float32)
        n1 = self.perlin.sample(xx * scale + t, yy * scale + t * 0.71)
        n2 = self.perlin.sample(xx * scale * 2.1 + 83.2, yy * scale * 2.1 - 41.7 + t * 0.31)
        self.noise_map = lerp(n1, n2, 0.30).astype(np.float32)

    def sample_noise_nearest(self, xs, ys):
        nx = np.clip(xs // cfg.NOISE_RESOLUTION_DIVISOR, 0, self.noise_w - 1)
        ny = np.clip(ys // cfg.NOISE_RESOLUTION_DIVISOR, 0, self.noise_h - 1)
        return self.noise_map[ny, nx]

    def smooth_noise_full_grid(self):
        return cv2.resize(self.noise_map, (self.w, self.h), interpolation=cv2.INTER_LINEAR)

    def create_seed_cluster(self, cx, cy, radius, roughness):
        min_x = max(0, cx - radius)
        max_x = min(self.w - 1, cx + radius)
        min_y = max(0, cy - radius)
        max_y = min(self.h - 1, cy + radius)

        inner = radius * (1.0 - roughness)
        radius_sq = radius * radius
        inner_sq = inner * inner

        yy, xx = np.mgrid[min_y:max_y + 1, min_x:max_x + 1]
        dx = xx - cx
        dy = yy - cy
        dist_sq = dx * dx + dy * dy

        inside = dist_sq <= radius_sq
        inner_mask = dist_sq <= inner_sq
        dist = np.sqrt(np.maximum(dist_sq.astype(np.float32), 0.0))

        if radius > inner:
            edge_t = np.clip((dist - inner) / (radius - inner), 0.0, 1.0)
        else:
            edge_t = np.zeros_like(dist, dtype=np.float32)

        chance = lerp(0.90, 0.15, edge_t)
        edge_random = self.rng.random(chance.shape)
        activate = inside & (inner_mask | (edge_random < chance))

        region = self.has_new_color[min_y:max_y + 1, min_x:max_x + 1]
        newly = activate & (~region)
        region[newly] = True
        self.active_cell_count += int(np.count_nonzero(newly))

    def generate_seeds(self):
        self.has_new_color.fill(False)
        self.active_cell_count = 0

        if cfg.USE_CLUSTERED_SEEDS:
            for _ in range(cfg.SEED_CLUSTER_COUNT):
                x = int(self.rng.integers(0, self.w))
                y = int(self.rng.integers(0, self.h))
                variation = float(self.rng.uniform(0.80, 1.20))
                radius = max(1, int(round(cfg.SEED_CLUSTER_RADIUS * variation)))
                self.create_seed_cluster(x, y, radius, cfg.CLUSTER_EDGE_ROUGHNESS)

        if cfg.USE_SECONDARY_CLUSTERS:
            min_var = max(0.05, 1.0 - cfg.SECONDARY_CLUSTER_SIZE_VARIATION)
            max_var = 1.0 + cfg.SECONDARY_CLUSTER_SIZE_VARIATION
            for _ in range(cfg.SECONDARY_CLUSTER_COUNT):
                x = int(self.rng.integers(0, self.w))
                y = int(self.rng.integers(0, self.h))
                variation = float(self.rng.uniform(min_var, max_var))
                radius = max(1, int(round(cfg.SECONDARY_CLUSTER_RADIUS * variation)))
                self.create_seed_cluster(x, y, radius, 0.45)

        for _ in range(cfg.EXTRA_RANDOM_SEED_COUNT):
            index = int(self.rng.integers(0, self.total_cells))
            y = index // self.w
            x = index % self.w
            if not self.has_new_color[y, x]:
                self.has_new_color[y, x] = True
                self.active_cell_count += 1

        if self.active_cell_count == 0:
            index = int(self.rng.integers(0, self.total_cells))
            y = index // self.w
            x = index % self.w
            self.has_new_color[y, x] = True
            self.active_cell_count = 1

    def frontier_coordinates(self):
        inactive = (~self.has_new_color).astype(np.uint8)
        kernel = np.ones((3, 3), dtype=np.uint8)
        near_inactive = cv2.dilate(inactive, kernel, iterations=1) > 0
        frontier_mask = self.has_new_color & near_inactive
        ys, xs = np.where(frontier_mask)
        count = len(xs)
        if count > cfg.MAX_FRONTIER_CELLS_PER_TICK:
            chosen = self.rng.choice(count, size=cfg.MAX_FRONTIER_CELLS_PER_TICK, replace=False)
            ys = ys[chosen]
            xs = xs[chosen]
        return xs.astype(np.int32), ys.astype(np.int32)

    def calculate_catchup_multiplier(self):
        if not cfg.USE_ADAPTIVE_CATCH_UP:
            return 1.0
        if self.elapsed_time <= cfg.CATCH_UP_START_TIME:
            return 1.0

        target_time = max(cfg.CATCH_UP_START_TIME + 0.1, cfg.IMAGE_CHANGE_INTERVAL)
        time_progress = float(np.clip((self.elapsed_time - cfg.CATCH_UP_START_TIME) / max(target_time - cfg.CATCH_UP_START_TIME, 1e-6), 0.0, 1.0))
        incomplete = 1.0 - self.spread_progress
        need_boost = float(np.clip(incomplete * 2.5, 0.0, 1.0))
        return float(lerp(1.0, cfg.CATCH_UP_MAX_MULTIPLIER, time_progress * need_boost))

    def calculate_dynamic_spread_radius(self, audio01, catchup):
        story_spread = max(0.0, self.story["spread"] - 1.0)
        story_value = story_spread * 0.6 + float(np.clip(self.story["noise"], 0.0, 1.0)) * 0.4
        catchup_radius = max(0.0, catchup - 1.0) * 0.7
        radius = cfg.BASE_SPREAD_RADIUS + audio01 * cfg.AUDIO_RADIUS_BOOST + story_value * cfg.STORY_RADIUS_BOOST + catchup_radius
        return int(np.clip(round(radius), 1, cfg.MAX_SPREAD_RADIUS))

    def calculate_dynamic_attempts(self, audio01, catchup):
        story01 = float(np.clip(self.story["spread"] - 1.0, 0.0, 1.0))
        catchup01 = 0.0 if cfg.CATCH_UP_MAX_MULTIPLIER <= 1.0 else float(np.clip((catchup - 1.0) / (cfg.CATCH_UP_MAX_MULTIPLIER - 1.0), 0.0, 1.0))
        attempts = (
            cfg.BASE_GROWTH_ATTEMPTS
            + int(round(audio01 * cfg.AUDIO_GROWTH_ATTEMPT_BONUS))
            + int(round(story01 * cfg.STORY_GROWTH_ATTEMPT_BONUS))
            + int(round(catchup01 * cfg.CATCH_UP_MAX_ADDITIONAL_ATTEMPTS))
        )
        return int(np.clip(attempts, 1, 16))

    def immediate_neighbor_fraction(self):
        active = self.has_new_color.astype(np.float32)
        kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.float32)
        count = cv2.filter2D(active, ddepth=-1, kernel=kernel, borderType=cv2.BORDER_CONSTANT)
        return count / 8.0

    def outer_neighbor_fraction(self, radius):
        active = self.has_new_color
        total = np.zeros((self.h, self.w), dtype=np.float32)

        for dx, dy in zip(DIRECTION_X, DIRECTION_Y):
            src = np.zeros_like(active)
            x_src_start = max(0, -dx * radius)
            x_src_end = min(self.w, self.w - dx * radius)
            y_src_start = max(0, -dy * radius)
            y_src_end = min(self.h, self.h - dy * radius)

            x_dst_start = x_src_start + dx * radius
            x_dst_end = x_src_end + dx * radius
            y_dst_start = y_src_start + dy * radius
            y_dst_end = y_src_end + dy * radius

            if x_src_start < x_src_end and y_src_start < y_src_end:
                src[y_dst_start:y_dst_end, x_dst_start:x_dst_end] = active[y_src_start:y_src_end, x_src_start:x_src_end]

            total += src.astype(np.float32)

        return total / 8.0

    def simulate_frontier_step(self, step_dt, audio_amplitude):
        xs, ys = self.frontier_coordinates()
        if len(xs) == 0:
            return

        audio01 = float(np.clip(audio_amplitude, 0.0, 1.0))
        catchup = self.calculate_catchup_multiplier()
        spread_radius = self.calculate_dynamic_spread_radius(audio01, catchup)
        attempts = self.calculate_dynamic_attempts(audio01, catchup)

        chance60 = float(np.clip((cfg.BASE_SPREAD_CHANCE + audio01 * cfg.AUDIO_SPREAD_BONUS) * max(0.05, self.story["spread"]) * catchup, 0.0, 1.0))
        base_chance = convert_60fps_chance_to_step(chance60, step_dt)

        dynamic_noise_weight = float(np.clip(
            cfg.NOISE_DRIVEN_WEIGHT
            + audio01 * cfg.AUDIO_NOISE_WEIGHT_BONUS
            + float(np.clip(self.story["noise"], 0.0, 1.0)) * cfg.STORY_NOISE_WEIGHT_BONUS,
            0.0, 1.0
        ))

        immediate_map = self.immediate_neighbor_fraction()
        organic_map = immediate_map if spread_radius <= 1 else immediate_map * 0.75 + self.outer_neighbor_fraction(spread_radius) * 0.25

        self.last_rule_debug["audio01"] = audio01
        self.last_rule_debug["radius"] = spread_radius
        self.last_rule_debug["attempts"] = attempts
        self.last_rule_debug["catchup"] = catchup

        n_sources = len(xs)

        for _ in range(attempts):
            directions = self.rng.integers(0, 8, size=n_sources)
            distances = self.rng.integers(1, spread_radius + 1, size=n_sources)
            dxs = DIRECTION_X[directions]
            dys = DIRECTION_Y[directions]
            continuing = np.ones(n_sources, dtype=bool)

            for step in range(1, spread_radius + 1):
                eligible = continuing & (distances >= step)
                if not np.any(eligible):
                    continue

                indices = np.where(eligible)[0]
                tx = xs[indices] + dxs[indices] * step
                ty = ys[indices] + dys[indices] * step

                in_bounds = (tx >= 0) & (tx < self.w) & (ty >= 0) & (ty < self.h)
                continuing[indices[~in_bounds]] = False
                if not np.any(in_bounds):
                    continue

                valid_indices = indices[in_bounds]
                tx = tx[in_bounds]
                ty = ty[in_bounds]

                already_active = self.has_new_color[ty, tx]
                inactive_mask = ~already_active
                if not np.any(inactive_mask):
                    continue

                eval_indices = valid_indices[inactive_mask]
                ex = tx[inactive_mask]
                ey = ty[inactive_mask]

                organic = organic_map[ey, ex]
                noise = self.sample_noise_nearest(ex, ey)

                noise_gate = np.clip((noise - cfg.SPREAD_NOISE_THRESHOLD) / max(1.0 - cfg.SPREAD_NOISE_THRESHOLD, 1e-6), 0.0, 1.0)
                noise_gate = noise_gate * noise_gate * (3.0 - 2.0 * noise_gate)

                shaped_organic = np.power(np.clip(organic, 0.0, 1.0), cfg.ORGANIC_INFLUENCE_POWER)
                organic_boost = lerp(0.72, 1.70, shaped_organic)
                noise_boost = lerp(0.62, 1.55, noise_gate)

                final_chance = base_chance * organic_boost * lerp(1.0, noise_boost, dynamic_noise_weight)
                final_chance = np.clip(final_chance, 0.0, 1.0)

                success = self.rng.random(len(ex)) < final_chance
                if np.any(success):
                    sx = ex[success]
                    sy = ey[success]
                    was_inactive = ~self.has_new_color[sy, sx]
                    self.has_new_color[sy, sx] = True
                    self.active_cell_count += int(np.count_nonzero(was_inactive))

                continuing[eval_indices[~success]] = False

    def update_original_reveal(self, dt):
        self.reveal_amount = 0.0

    def blend_random_neighbors(self, dt):
        chance = cfg.NEIGHBOR_BLEND_CHANCE * self.story["blend"] * dt * 30.0
        if chance <= 0.0:
            return

        choose = self.has_new_color & (self.rng.random((self.h, self.w)) < chance)
        ys, xs = np.where(choose)
        if len(xs) == 0:
            return

        directions = self.rng.integers(0, 8, size=len(xs))
        nx = xs + DIRECTION_X[directions]
        ny = ys + DIRECTION_Y[directions]
        valid = (nx >= 0) & (nx < self.w) & (ny >= 0) & (ny < self.h)
        if not np.any(valid):
            return

        xs, ys, nx, ny = xs[valid], ys[valid], nx[valid], ny[valid]
        self.current_colors[ys, xs] = lerp(self.current_colors[ys, xs], self.current_colors[ny, nx], cfg.NEIGHBOR_BLEND_AMOUNT)

    def apply_ambient_drift(self, dt, audio_amplitude):
        self.last_rule_debug["ambientChance"] = 0.0
        self.last_rule_debug["ambientActive"] = 0

        if not cfg.USE_AMBIENT_DRIFT:
            return
        if self.spread_progress < cfg.AMBIENT_DRIFT_START_PROGRESS:
            return

        active = self.has_new_color
        if not np.any(active):
            return

        # 경계선 추출: active 셀 중 inactive 이웃이 있는 부분
        inactive = (~active).astype(np.uint8)
        near_inactive = cv2.dilate(inactive, np.ones((3, 3), dtype=np.uint8), iterations=1) > 0
        edge_mask = active & near_inactive

        audio01 = float(np.clip(audio_amplitude, 0.0, 1.0))
        story_noise01 = float(np.clip(self.story["noise"], 0.0, 1.0))
        story_spread01 = float(np.clip(self.story["spread"] - 1.0, 0.0, 1.0))

        chance30 = (
            cfg.AMBIENT_DRIFT_BASE_CHANCE
            + story_noise01 * cfg.AMBIENT_DRIFT_STORY_NOISE_BONUS
            + story_spread01 * cfg.AMBIENT_DRIFT_STORY_SPREAD_BONUS
            + audio01 * cfg.AMBIENT_DRIFT_AUDIO_BONUS
        )

        progress01 = float(np.clip((self.spread_progress - cfg.AMBIENT_DRIFT_START_PROGRESS) / max(1.0 - cfg.AMBIENT_DRIFT_START_PROGRESS, 1e-6), 0.0, 1.0))
        chance30 *= lerp(0.6, 1.0, progress01)

        chance = 1.0 - math.pow(1.0 - np.clip(chance30, 0.0, 0.95), dt * 30.0)
        base_prob = np.full((self.h, self.w), chance, dtype=np.float32)

        if np.any(edge_mask):
            base_prob[edge_mask] *= cfg.AMBIENT_EDGE_BONUS

        full_noise = self.smooth_noise_full_grid()
        noise_factor = lerp(1.0 - cfg.AMBIENT_NOISE_GATE_WEIGHT, 1.0 + cfg.AMBIENT_NOISE_GATE_WEIGHT, full_noise)
        prob = np.clip(base_prob * noise_factor, 0.0, 0.95)

        choose = active & (self.rng.random((self.h, self.w)) < prob)
        ys, xs = np.where(choose)
        if len(xs) == 0:
            self.last_rule_debug["ambientChance"] = float(chance)
            return

        directions = self.rng.integers(0, 8, size=len(xs))
        nx = xs + DIRECTION_X[directions]
        ny = ys + DIRECTION_Y[directions]

        # NumPy는 아래처럼 쓰면:
        # (범위 체크) & active[ny, nx]
        # active[ny, nx]를 먼저 평가할 수 있어서
        # ny == self.h 또는 nx == self.w인 순간 IndexError가 발생합니다.
        #
        # 따라서 1) 좌표 범위 검사
        #       2) 범위 안의 좌표만 active 배열에 접근
        # 순서로 나눠 처리합니다.
        in_bounds = (
            (nx >= 0)
            & (nx < self.w)
            & (ny >= 0)
            & (ny < self.h)
        )

        if not np.any(in_bounds):
            self.last_rule_debug["ambientChance"] = float(chance)
            return

        valid = np.zeros(len(xs), dtype=bool)
        inside_indices = np.where(in_bounds)[0]

        valid[inside_indices] = active[
            ny[inside_indices],
            nx[inside_indices],
        ]

        if not np.any(valid):
            self.last_rule_debug["ambientChance"] = float(chance)
            return

        xs, ys, nx, ny = xs[valid], ys[valid], nx[valid], ny[valid]
        blend = cfg.AMBIENT_DRIFT_NEIGHBOR_BLEND
        self.current_colors[ys, xs] = lerp(self.current_colors[ys, xs], self.current_colors[ny, nx], blend)

        # target으로 다시 복귀 -> 원형 유지
        self.current_colors[ys, xs] = lerp(self.current_colors[ys, xs], self.target_colors[ys, xs], cfg.AMBIENT_RETURN_TO_TARGET)

        self.last_rule_debug["ambientChance"] = float(chance)
        self.last_rule_debug["ambientActive"] = int(len(xs))

    def render_texture(self, render_dt, audio_amplitude):
        color_speed = cfg.BASE_COLOR_LERP_SPEED + float(np.clip(audio_amplitude, 0.0, 1.0)) * cfg.AUDIO_COLOR_LERP_BONUS
        catchup = self.calculate_catchup_multiplier()
        catchup01 = 0.0 if cfg.CATCH_UP_MAX_MULTIPLIER <= 1.0 else float(np.clip((catchup - 1.0) / (cfg.CATCH_UP_MAX_MULTIPLIER - 1.0), 0.0, 1.0))

        color_speed *= float(lerp(1.0, 1.6, catchup01))
        color_lerp_t = 1.0 - math.exp(-color_speed * render_dt)

        active = self.has_new_color
        self.current_colors[active] = lerp(self.current_colors[active], self.target_colors[active], color_lerp_t)

        self.blend_random_neighbors(render_dt)
        self.apply_ambient_drift(render_dt, audio_amplitude)

        current_source = self.current_colors

        distortion = cfg.USE_STORY_DISTORTION and self.story["noise"] > 0.01
        if distortion:
            full_noise = self.smooth_noise_full_grid()
            noise_a = full_noise * 2.0 - 1.0
            noise_b = np.flip(np.flip(full_noise, axis=0), axis=1) * 2.0 - 1.0

            offset_x = np.rint(noise_a * cfg.NOISE_PIXEL_OFFSET * self.story["noise"]).astype(np.float32)
            offset_y = np.rint(noise_b * cfg.NOISE_PIXEL_OFFSET * self.story["noise"]).astype(np.float32)

            grid_x, grid_y = np.meshgrid(np.arange(self.w, dtype=np.float32), np.arange(self.h, dtype=np.float32))
            map_x = np.clip(grid_x + offset_x, 0, self.w - 1).astype(np.float32)
            map_y = np.clip(grid_y + offset_y, 0, self.h - 1).astype(np.float32)

            current_source = cv2.remap(current_source, map_x, map_y, interpolation=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)

        color = current_source
        gray = color[..., 0] * 0.299 + color[..., 1] * 0.587 + color[..., 2] * 0.114
        gray3 = np.repeat(gray[..., None], 3, axis=2)
        color = gray3 + (color - gray3) * self.story["saturation"]
        color *= self.story["brightness"]
        color *= self.story["fade"]
        return clamp01(color).astype(np.float32)

    def calculate_color_completion(self):
        stride = max(1, cfg.COMPLETION_SAMPLE_STRIDE)
        current = self.current_colors[::stride, ::stride]
        target = self.target_colors[::stride, ::stride]
        active = self.has_new_color[::stride, ::stride]

        difference = np.mean(np.abs(current - target), axis=2)
        error = np.where(active, difference, 1.0)
        self.color_completion_progress = float(np.clip(1.0 - np.mean(error), 0.0, 1.0))

    def start_next_image(self):
        self.elapsed_time = 0.0
        self.reveal_amount = 0.0
        self.color_completion_progress = 0.0
        self.current_image_index = (self.current_image_index + 1) % len(self.targets)
        self.target_colors = self.targets[self.current_image_index].copy()
        self.generate_seeds()

    def update(self, global_time, dt, audio_amplitude):
        self.story_sentence, self.story, self.story_detected = self.story_controller.state_at(
            self.current_image_index,
            self.elapsed_time,
        )
        self.elapsed_time += dt
        self.update_original_reveal(dt)

        self.noise_timer += dt
        noise_interval = 1.0 / max(1, cfg.NOISE_UPDATE_FPS)
        if self.noise_timer >= noise_interval:
            self.noise_timer = 0.0
            self.update_cached_noise_map(global_time)

        self.simulation_timer += dt
        sim_interval = 1.0 / max(1, cfg.SIMULATION_FPS)
        if self.simulation_timer >= sim_interval:
            self.simulation_timer = 0.0
            self.simulate_frontier_step(sim_interval, audio_amplitude)

        frame_grid = self.render_texture(dt, audio_amplitude)
        self.calculate_color_completion()
        return frame_grid


def grid_rgb_to_output_bgr(grid_rgb):
    rgb8 = np.clip(grid_rgb * 255.0, 0, 255).astype(np.uint8)

    up_rgb = cv2.resize(
        rgb8,
        (cfg.UPSCALED_WIDTH, cfg.UPSCALED_HEIGHT),
        interpolation=cv2.INTER_NEAREST if getattr(cfg, "USE_NEAREST_UPSCALE", True) else cv2.INTER_LINEAR,
    )

    canvas = np.full(
        (cfg.OUTPUT_HEIGHT, cfg.OUTPUT_WIDTH, 3),
        int(np.clip(cfg.PAD_BACKGROUND, 0.0, 1.0) * 255),
        dtype=np.uint8,
    )

    pad_x = (cfg.OUTPUT_WIDTH - cfg.UPSCALED_WIDTH) // 2
    pad_y = (cfg.OUTPUT_HEIGHT - cfg.UPSCALED_HEIGHT) // 2
    canvas[pad_y:pad_y + cfg.UPSCALED_HEIGHT, pad_x:pad_x + cfg.UPSCALED_WIDTH] = up_rgb

    return cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)


class ObjectOverlayManager:
    """
    scene별 오브제를 순서대로 표시합니다.

    중요한 규칙:
    - 다른 scene의 오브제는 섞지 않음
    - scene 안에서는 dream_scenes.json의 objects 순서대로 표시
    - 오브제가 없는 시간 없음
    - scene 75초를 오브제 수로 나눠 각 오브제의 표시 시간을 자동 결정
    - 각 오브제는 자신의 표시 구간 동안 하나의 랜덤 좌표에 고정
    """

    def __init__(self, scene_manifest, output_w, output_h):
        self.scene_manifest = scene_manifest
        self.output_w = output_w
        self.output_h = output_h
        self.enabled = cfg.USE_OBJECT_OVERLAY

        self.rng = np.random.default_rng(cfg.OBJECT_RANDOM_SEED)
        self.schedule_by_scene = {}

        if not self.enabled:
            return

        self.build_schedule()

    def _prepare_scaled_object(self, path: Path):
        rgba = read_object_image(path)

        h, w = rgba.shape[:2]

        max_w = max(1, int(self.output_w * cfg.OBJECT_MAX_WIDTH_RATIO))
        max_h = max(1, int(self.output_h * cfg.OBJECT_MAX_HEIGHT_RATIO))

        random_scale = float(
            self.rng.uniform(
                cfg.OBJECT_MIN_SCALE,
                cfg.OBJECT_MAX_SCALE,
            )
        )

        desired_w = max(1, int(round(w * random_scale)))
        desired_h = max(1, int(round(h * random_scale)))

        fit_scale = min(
            max_w / desired_w,
            max_h / desired_h,
            1.0,
        )

        new_w = max(1, int(round(desired_w * fit_scale)))
        new_h = max(1, int(round(desired_h * fit_scale)))

        interpolation = (
            cv2.INTER_AREA
            if new_w < w or new_h < h
            else cv2.INTER_LINEAR
        )

        return cv2.resize(
            rgba,
            (new_w, new_h),
            interpolation=interpolation,
        )

    def _random_position(self, rgba):
        h, w = rgba.shape[:2]

        margin_x = int(self.output_w * cfg.OBJECT_MARGIN_RATIO)
        margin_y = int(self.output_h * cfg.OBJECT_MARGIN_RATIO)

        min_x = max(0, margin_x)
        min_y = max(0, margin_y)

        max_x = max(min_x, self.output_w - w - margin_x)
        max_y = max(min_y, self.output_h - h - margin_y)

        x = (
            int(self.rng.integers(min_x, max_x + 1))
            if max_x > min_x
            else min_x
        )
        y = (
            int(self.rng.integers(min_y, max_y + 1))
            if max_y > min_y
            else min_y
        )

        return x, y

    def build_schedule(self):
        for scene_index, scene in enumerate(self.scene_manifest):
            paths = scene["object_paths"]
            names = scene["object_names"]

            if not paths:
                raise ValueError(
                    f"scene_{scene['scene']:02d}에 오브제가 없습니다. "
                    "현재 모델은 '오브제가 없는 시간 없음' 규칙을 사용합니다."
                )

            count = len(paths)
            duration = cfg.IMAGE_CHANGE_INTERVAL / count

            entries = []

            for object_index, (name, path) in enumerate(
                zip(names, paths)
            ):
                rgba = self._prepare_scaled_object(path)
                x, y = self._random_position(rgba)

                start = object_index * duration
                end = (
                    cfg.IMAGE_CHANGE_INTERVAL
                    if object_index == count - 1
                    else (object_index + 1) * duration
                )

                entries.append(
                    {
                        "scene_index": scene_index,
                        "scene_number": scene["scene"],
                        "object_index": object_index,
                        "name": name,
                        "path": path,
                        "rgba": rgba,
                        "x": x,
                        "y": y,
                        "start": float(start),
                        "end": float(end),
                    }
                )

            self.schedule_by_scene[scene_index] = entries

    def entry_at(self, scene_index, scene_local_time):
        if not self.enabled:
            return None

        entries = self.schedule_by_scene.get(scene_index, [])
        if not entries:
            return None

        scene_local_time = float(
            np.clip(
                scene_local_time,
                0.0,
                cfg.IMAGE_CHANGE_INTERVAL - 1e-6,
            )
        )

        # 각 scene 전체를 object count로 균등 분할
        duration = cfg.IMAGE_CHANGE_INTERVAL / len(entries)
        index = min(
            int(scene_local_time // duration),
            len(entries) - 1,
        )

        return entries[index]

    def apply(self, frame_bgr, scene_index, scene_local_time):
        entry = self.entry_at(scene_index, scene_local_time)

        if entry is None:
            return frame_bgr, None

        rgba = entry["rgba"]
        x = entry["x"]
        y = entry["y"]

        h, w = rgba.shape[:2]

        rgb = np.clip(
            rgba[..., :3] * 255.0,
            0,
            255,
        ).astype(np.uint8)

        bgr = cv2.cvtColor(
            rgb,
            cv2.COLOR_RGB2BGR,
        )

        alpha = np.clip(
            rgba[..., 3:4],
            0.0,
            1.0,
        ).astype(np.float32)

        y2 = min(frame_bgr.shape[0], y + h)
        x2 = min(frame_bgr.shape[1], x + w)

        if y2 <= y or x2 <= x:
            return frame_bgr, entry

        roi = frame_bgr[y:y2, x:x2].astype(np.float32)
        obj = bgr[: y2 - y, : x2 - x].astype(np.float32)
        a = alpha[: y2 - y, : x2 - x]

        blended = obj * a + roi * (1.0 - a)

        frame_bgr[y:y2, x:x2] = np.clip(
            blended,
            0,
            255,
        ).astype(np.uint8)

        return frame_bgr, entry


def merge_audio(silent_path: Path, audio_path: Path, final_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("[FFmpeg] ffmpeg를 찾지 못했습니다. silent 영상만 생성합니다.")
        return False

    cmd = [
        ffmpeg, "-y",
        "-i", str(silent_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(final_path),
    ]
    subprocess.run(cmd, check=True)
    return True


def main():
    scene_manifest = load_scene_manifest()
    image_paths = load_image_paths(scene_manifest)
    audio_path = find_audio_file()

    story = StoryController(scene_manifest)
    audio = AudioAnalyzer(audio_path)
    model = DreamGridModel(image_paths, story, audio)

    object_manager = ObjectOverlayManager(
        scene_manifest=scene_manifest,
        output_w=cfg.OUTPUT_WIDTH,
        output_h=cfg.OUTPUT_HEIGHT,
    )

    silent_path = cfg.OUT_DIR / cfg.OUTPUT_SILENT_NAME
    final_path = cfg.OUT_DIR / cfg.OUTPUT_FINAL_NAME
    log_path = cfg.OUT_DIR / cfg.OUTPUT_LOG_NAME

    writer = cv2.VideoWriter(
        str(silent_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        cfg.VIDEO_FPS,
        (cfg.OUTPUT_WIDTH, cfg.OUTPUT_HEIGHT),
    )
    if not writer.isOpened():
        raise RuntimeError("VideoWriter를 열지 못했습니다.")

    dt = 1.0 / cfg.VIDEO_FPS
    global_time = 0.0
    # 배경 개수 × 75초를 기준으로 렌더 길이를 계산합니다.
    # MAX_RENDER_SECONDS보다 짧게 잘려 배경4가 누락되는 일을 방지합니다.
    sequence_seconds = len(image_paths) * cfg.IMAGE_CHANGE_INTERVAL + cfg.FINAL_IMAGE_HOLD_TIME
    max_render_seconds = max(cfg.MAX_RENDER_SECONDS, sequence_seconds + 1.0)
    max_frames = int(math.ceil(max_render_seconds * cfg.VIDEO_FPS))

    last_audio_print = -999.0
    last_debug_print = -999.0
    last_story_text = None
    last_object_key = None

    logs = []
    final_hold_timer = 0.0
    done = False

    print("====================================================")
    print(" GridModel v2 — storyboard scene input")
    print(f" CA Grid   : {cfg.GRID_WIDTH} x {cfg.GRID_HEIGHT}")
    print(f" Upscaled  : {cfg.UPSCALED_WIDTH} x {cfg.UPSCALED_HEIGHT}")
    print(f" Output    : {cfg.OUTPUT_WIDTH} x {cfg.OUTPUT_HEIGHT}")
    print(f" Input     : {cfg.INPUT_DIR}")
    print(f" Storyboard: {cfg.STORYBOARD_DIR}")
    print(f" Objects   : {cfg.OBJECTS_DIR}")
    print(f" Scenes    : {len(scene_manifest)}")
    print(f" Audio     : {audio_path.name if audio_path else '없음'}")
    print(f" Sequence  : scene_01~04 각 {cfg.IMAGE_CHANGE_INTERVAL:.0f}초, 총 {len(scene_manifest) * cfg.IMAGE_CHANGE_INTERVAL:.0f}초")
    print("====================================================")

    try:
        for _ in tqdm(range(max_frames), desc="Render v2"):
            audio_amp = audio.update(global_time, dt)
            frame_grid = model.update(global_time, dt, audio_amp)

            if model.story_sentence != last_story_text:
                keyword_text = " / ".join(model.story_detected) if model.story_detected else "없음"
                message = f"[Story] {global_time:6.2f}s | {model.story_sentence} | 키워드: {keyword_text}"
                print("\n" + message)
                logs.append(message)
                last_story_text = model.story_sentence

            if global_time - last_audio_print >= cfg.PRINT_AUDIO_EVERY_SEC:
                print(f"\n[Audio] {global_time:6.2f}s | Amplitude={audio_amp:.4f}")
                last_audio_print = global_time

            if global_time - last_debug_print >= cfg.PRINT_DEBUG_EVERY_SEC:
                d = model.last_rule_debug
                message = (
                    f"[CA] img={model.current_image_index + 1} | "
                    f"elapsed={model.elapsed_time:.2f}s | "
                    f"spread={model.spread_progress:.4f} | "
                    f"colorCompletion={model.color_completion_progress:.4f} | "
                    f"radius={d['radius']} | attempts={d['attempts']} | catchup={d['catchup']:.2f} | "
                    f"ambientChance={d['ambientChance']:.5f} | ambientActive={d['ambientActive']}"
                )
                print("\n" + message)
                logs.append(message)
                last_debug_print = global_time

            frame_bgr = grid_rgb_to_output_bgr(frame_grid)

            frame_bgr, object_entry = object_manager.apply(
                frame_bgr,
                model.current_image_index,
                model.elapsed_time,
            )

            if object_entry is not None:
                object_key = (
                    object_entry["scene_number"],
                    object_entry["object_index"],
                )

                if object_key != last_object_key:
                    object_duration = (
                        object_entry["end"]
                        - object_entry["start"]
                    )
                    message = (
                        f"[Object] scene_{object_entry['scene_number']:02d} | "
                        f"{object_entry['object_index'] + 1}: {object_entry['name']} | "
                        f"{object_duration:.2f}s | "
                        f"pos=({object_entry['x']},{object_entry['y']})"
                    )
                    print("\n" + message)
                    logs.append(message)
                    last_object_key = object_key

            writer.write(frame_bgr)

            is_last_image = (model.current_image_index == len(image_paths) - 1)

            if cfg.USE_FORCED_TIME_SEQUENCE:
                if model.elapsed_time >= cfg.IMAGE_CHANGE_INTERVAL:
                    if cfg.STOP_AFTER_LAST_IMAGE and is_last_image:
                        # 마지막 scene이 75초 끝나면 바로 종료
                        final_hold_timer += dt
                        if final_hold_timer >= cfg.FINAL_IMAGE_HOLD_TIME:
                            done = True
                    else:
                        old_index = model.current_image_index
                        model.start_next_image()
                        final_hold_timer = 0.0
                        last_story_text = None
                        last_object_key = None
                        message = f"[ImageChange] {old_index + 1} -> {model.current_image_index + 1} at {global_time:.2f}s (forced {cfg.IMAGE_CHANGE_INTERVAL:.0f}s)"
                        print("\n" + message)
                        logs.append(message)
                else:
                    final_hold_timer = 0.0

            if done:
                print("\n[Done] 마지막 이미지까지 렌더 완료")
                break

            global_time += dt

    finally:
        writer.release()

    log_path.write_text("\n".join(logs), encoding="utf-8")

    print(f"\nsilent: {silent_path}")
    print(f"log   : {log_path}")

    if audio_path is not None:
        try:
            if merge_audio(silent_path, audio_path, final_path):
                print(f"final  : {final_path}")
        except subprocess.CalledProcessError as e:
            print("[FFmpeg] 오디오 합성 중 오류:", e)
    else:
        print("[Audio] 오디오 파일이 없어 silent 영상만 생성했습니다.")


if __name__ == "__main__":
    main()
