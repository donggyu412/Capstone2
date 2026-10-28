# -*- coding: utf-8 -*-
"""Constructive RGB-state animation: bounded single-seed descendants, target-guided genetic evolution, local cellular colour rules, and forward-transported debris. Utilities for sound, image I/O and older render paths remain available."""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F


def resolve_ffmpeg() -> str:
    """시스템 PATH, imageio_ffmpeg, 또는 로컬 경로에서 실행 가능한 ffmpeg 바이너리를 탐색."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    fallback = Path(r"C:\Users\carro\Documents\Codex\2026-09-30\v\outputs\System-V\vendor\ffmpeg\ffmpeg.exe")
    if fallback.exists():
        return str(fallback)
    return "ffmpeg"


FFMPEG = resolve_ffmpeg()

# --------------------------------------------------------------------------------------
# 기본 시공간 규격 (표준 5분 = 300초, 4막 × 75초, 프리뷰 시 스케일 가능)
# --------------------------------------------------------------------------------------
W, H, FPS, DUR = 1920, 1080, 30, 300.0
N = int(FPS * DUR)
DT = 1.0 / FPS

# CA 격자 (320 x 180, 6px 셀) 및 GA 스트로크 작업 격자 (480 x 270, 4px 셀)
CELL = 6
GW, GH = W // CELL, H // CELL            # 320 x 180
GA_W, GA_H = 480, 270                    # 480 x 270 (고속 GPU 벡터 스플래팅 격자)

SCENE_T = [0.0, 75.0, 150.0, 225.0, 300.0]
CLIMAX = 195.0                           # 표준 3막 45초 지점 (전체 3분 15초)
PRE, POST = 5.5, 7.5                     # 장면 간 기억 유산 전이 구간
DEV = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.backends.cudnn.benchmark = True

EMO_KO = {
    "기쁨": "happy",
    "슬픔": "sad",
    "분노": "angry",
    "공포": "fear",
    "놀람": "surprise",
    "혐오": "disgust",
    "중립": "neutral",
}

# 감정별 기본 동역학 성향 (고정 색 필터가 아닌 진화/붕괴/호흡/흐름 파라미터로 작동)
EMO = {
    "neutral":  dict(grow=1.00, decay=0.72, jitter=0.06, breath=0.18, flow=0.65,
                     warm=0.00, sat=1.02, flash=0.18, twist=0.04, mut=0.65, collapse=0.55, speed=0.85),
    "happy":    dict(grow=1.42, decay=0.52, jitter=0.10, breath=0.32, flow=1.05,
                     warm=0.14, sat=1.18, flash=0.35, twist=0.05, mut=0.82, collapse=0.38, speed=1.10),
    "sad":      dict(grow=0.72, decay=0.58, jitter=0.05, breath=0.15, flow=0.48,
                     warm=-0.10, sat=0.84, flash=0.10, twist=0.03, mut=0.52, collapse=0.46, speed=0.62),
    "angry":    dict(grow=1.58, decay=1.35, jitter=0.55, breath=0.48, flow=1.75,
                     warm=0.12, sat=1.22, flash=0.62, twist=0.28, mut=1.45, collapse=1.28, speed=1.55),
    "fear":     dict(grow=0.92, decay=1.18, jitter=0.38, breath=0.28, flow=1.15,
                     warm=-0.08, sat=0.92, flash=0.32, twist=0.22, mut=1.22, collapse=1.18, speed=1.22),
    "surprise": dict(grow=1.48, decay=0.92, jitter=0.26, breath=0.46, flow=1.30,
                     warm=0.04, sat=1.14, flash=0.78, twist=0.14, mut=1.12, collapse=0.88, speed=1.35),
    "disgust":  dict(grow=0.88, decay=1.12, jitter=0.28, breath=0.24, flow=0.88,
                     warm=-0.03, sat=0.88, flash=0.22, twist=0.42, mut=1.28, collapse=1.05, speed=0.95),
}


def emo_params(label_en: str, intensity: float) -> dict:
    """중립(neutral)을 기준점으로 감정 강도(intensity)에 비례해 동역학 파라미터를 보간."""
    k = float(np.clip(intensity / 0.55, 0.25, 1.45))
    base = EMO["neutral"]
    e = EMO.get(label_en, base)
    return {key: base[key] + (e[key] - base[key]) * k for key in base}


def mix_params(a: dict, b: dict, w: float) -> dict:
    return {k: a[k] + (b[k] - a[k]) * w for k in a}


# --------------------------------------------------------------------------------------
# 영상·수치 유틸리티 (NumPy / PyTorch GPU)
# --------------------------------------------------------------------------------------
YY, XX = np.mgrid[0:H, 0:W].astype(np.float32)
U, V = XX / W, YY / H


def hexc(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], np.float32)


def blur(a: np.ndarray, s: float) -> np.ndarray:
    if s <= 0:
        return a
    return cv2.GaussianBlur(a, (0, 0), s)


def vnoise(seed: int, scale: int, w: int = W, h: int = H) -> np.ndarray:
    rng = np.random.default_rng(seed)
    gh, gw = max(2, h // scale + 4), max(2, w // scale + 4)
    small = rng.random((gh, gw)).astype(np.float32)
    big = cv2.resize(small, (gw * scale, gh * scale), interpolation=cv2.INTER_CUBIC)
    return np.clip(big[scale:scale + h, scale:scale + w], 0.0, 1.0)


def fbm(seed: int, scales=(240, 120, 60, 30), w: int = W, h: int = H) -> np.ndarray:
    acc, amp, tot = 0.0, 1.0, 0.0
    for i, s in enumerate(scales):
        acc = acc + vnoise(seed + i * 17, max(4, s), w, h) * amp
        tot += amp
        amp *= 0.55
    return (acc / max(tot, 1e-6)).astype(np.float32)


def cellular_fracture_map(
    seed: int,
    n_cells: int = 86,
    w: int = W,
    h: int = H,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    불규칙 셀룰러 붕괴 시 공간이 모래알처럼 부서지지 않고 선명한 건축/자연 단층 판(slab) 단위로
    갈라져 미끄러지도록 보로노이 균열 경계(crack), 셀 위상(cid), 셀별 강체 낙하 편차 벡터(svx, svy)를 생성.
    """
    rng = np.random.default_rng(seed)
    sw, sh = w // 4, h // 4
    pts_x = rng.uniform(0, sw, n_cells).astype(np.float32)
    pts_y = rng.uniform(0, sh, n_cells).astype(np.float32)
    cell_val = rng.uniform(0.15, 1.0, n_cells).astype(np.float32)
    cell_vx = rng.uniform(-0.048, 0.048, n_cells).astype(np.float32)
    cell_vy = rng.uniform(0.015, 0.085, n_cells).astype(np.float32)

    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    # 워프 노이즈로 직선 보로노이를 자연스러운 암석/기억 단층 균열선으로 굴절
    wx = xx + (fbm(seed + 5, (48, 24, 12), w=sw, h=sh) - 0.5) * 26.0
    wy = yy + (fbm(seed + 9, (48, 24, 12), w=sw, h=sh) - 0.5) * 26.0

    dx = wx[..., None] - pts_x[None, None, :]
    dy = wy[..., None] - pts_y[None, None, :]
    d2 = dx * dx + dy * dy
    idx2 = np.argpartition(d2, 2, axis=-1)[..., :2]
    d_first = np.sqrt(np.take_along_axis(d2, idx2[..., 0:1], axis=-1)[..., 0])
    d_second = np.sqrt(np.take_along_axis(d2, idx2[..., 1:2], axis=-1)[..., 0])

    first_id = idx2[..., 0]
    crack = np.exp(-np.clip(d_second - d_first, 0.0, 20.0) / 1.9).astype(np.float32)
    cid = cell_val[first_id].astype(np.float32)
    svx = cell_vx[first_id].astype(np.float32)
    svy = cell_vy[first_id].astype(np.float32)

    crack_full = cv2.resize(crack, (w, h), interpolation=cv2.INTER_LINEAR)
    cid_full = cv2.resize(cid, (w, h), interpolation=cv2.INTER_NEAREST)
    svx_full = cv2.resize(svx, (w, h), interpolation=cv2.INTER_NEAREST)
    svy_full = cv2.resize(svy, (w, h), interpolation=cv2.INTER_NEAREST)
    return crack_full, cid_full, svx_full, svy_full


def imread_u(path: Path) -> np.ndarray:
    """유니코드(한글) 경로를 안전하게 지원하며 1920x1080 float32 RGB(0..1)로 로드."""
    raw = np.fromfile(str(path), np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"배경 이미지를 읽을 수 없습니다: {path}")
    if img.shape[1] != W or img.shape[0] != H:
        interp = cv2.INTER_CUBIC if img.shape[1] < W else cv2.INTER_AREA
        img = cv2.resize(img, (W, H), interpolation=interp)
    return img[..., ::-1].astype(np.float32) / 255.0


def T(a) -> torch.Tensor:
    a = np.asarray(a, np.float32)
    a = a[None] if a.ndim == 2 else a.transpose(2, 0, 1)
    return torch.from_numpy(np.ascontiguousarray(a))[None].to(DEV)


def col(h: str) -> torch.Tensor:
    return torch.tensor(hexc(h), device=DEV).view(1, 3, 1, 1)


def lum(x: torch.Tensor) -> torch.Tensor:
    return 0.299 * x[:, 0:1] + 0.587 * x[:, 1:2] + 0.114 * x[:, 2:3]


_GK: dict[tuple[float, torch.device], torch.Tensor] = {}


def gblur(x: torch.Tensor, sigma: float) -> torch.Tensor:
    if sigma <= 0:
        return x
    key = (round(float(sigma), 3), x.device)
    if key not in _GK:
        k = max(3, int(sigma * 3) * 2 + 1)
        ax = torch.arange(k, device=x.device, dtype=torch.float32) - k // 2
        g = torch.exp(-(ax ** 2) / (2 * sigma ** 2))
        _GK[key] = g / g.sum()
    g = _GK[key]
    k = g.numel()
    C = x.shape[1]
    x = F.conv2d(F.pad(x, (k // 2, k // 2, 0, 0), mode="replicate"), g.view(1, 1, 1, k).repeat(C, 1, 1, 1), groups=C)
    x = F.conv2d(F.pad(x, (0, 0, k // 2, k // 2), mode="replicate"), g.view(1, 1, k, 1).repeat(C, 1, 1, 1), groups=C)
    return x


def down(x: torch.Tensor, h: int = GH, w: int = GW) -> torch.Tensor:
    return F.interpolate(x, size=(h, w), mode="area")


def up(x: torch.Tensor, h: int = H, w: int = W) -> torch.Tensor:
    return F.interpolate(x, size=(h, w), mode="bilinear", align_corners=False)


def ss(e0: float, e1: float, x: float) -> float:
    if abs(e1 - e0) < 1e-9:
        return 1.0 if x >= e1 else 0.0
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def tss(e0: float, e1: float, x: torch.Tensor) -> torch.Tensor:
    t = ((x - e0) / max(e1 - e0, 1e-6)).clamp(0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def gauss(t: float, c: float, w: float) -> float:
    return math.exp(-((t - c) / max(w, 1e-5)) ** 2)


PXT = torch.arange(W, device=DEV, dtype=torch.float32).view(1, W).expand(H, W) + 0.5
PYT = torch.arange(H, device=DEV, dtype=torch.float32).view(H, 1).expand(H, W) + 0.5
UT, VT = (PXT / W)[None, None], (PYT / H)[None, None]

# 작업 격자 좌표 (GA 480x270, CA 320x180)
GA_U = (torch.arange(GA_W, device=DEV, dtype=torch.float32).view(1, GA_W) + 0.5) / GA_W
GA_V = (torch.arange(GA_H, device=DEV, dtype=torch.float32).view(GA_H, 1) + 0.5) / GA_H
CA_U = (torch.arange(GW, device=DEV, dtype=torch.float32).view(1, 1, 1, GW) + 0.5) / GW
CA_V = (torch.arange(GH, device=DEV, dtype=torch.float32).view(1, 1, GH, 1) + 0.5) / GH


# --------------------------------------------------------------------------------------
# 다대역 사운드 분석기
# --------------------------------------------------------------------------------------
def ema(a: np.ndarray, tau: float) -> np.ndarray:
    k = 1.0 - math.exp(-DT / max(tau, 1e-4))
    y = np.zeros_like(a)
    acc = float(a[0]) if len(a) else 0.0
    for i in range(len(a)):
        acc += (float(a[i]) - acc) * k
        y[i] = acc
    return y


def analyze_sound(path: Path, total_frames: int = N) -> dict:
    """오디오/비디오 파일에서 48kHz 파형을 추출하여 저음/중음/고음 에너지 및 Onset 충격 신호를 계산."""
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    x = np.frombuffer(raw, np.float32).copy()
    sr, hop, win = 48000, 48000 // FPS, 4096
    need = total_frames * hop + win
    if len(x) == 0:
        x = np.zeros(need, np.float32)
    x = np.pad(x, (win // 2, max(0, need - len(x) - win // 2)))
    hann = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    bands = {"low": (20, 180), "mid": (180, 1200), "high": (1200, 8000)}
    out = {k: np.zeros(total_frames, np.float32) for k in bands}
    flux = np.zeros(total_frames, np.float32)
    rms = np.zeros(total_frames, np.float32)
    fmask = (freqs >= 150) & (freqs < 10000)
    prev = None
    for c0 in range(0, total_frames, 600):
        c1 = min(total_frames, c0 + 600)
        idx = (np.arange(c0, c1) * hop)[:, None] + np.arange(win)[None]
        seg = x[idx] * hann
        sp = np.abs(np.fft.rfft(seg, axis=1)).astype(np.float32)
        for k, (a, b) in bands.items():
            out[k][c0:c1] = sp[:, (freqs >= a) & (freqs < b)].mean(1)
        ls = np.log1p(sp * 20.0)
        full = np.vstack([ls[:1] if prev is None else prev[None], ls])
        flux[c0:c1] = np.maximum(np.diff(full, axis=0), 0.0)[:, fmask].mean(1)
        prev = ls[-1]
        rms[c0:c1] = np.sqrt((seg ** 2).mean(1))

    def norm(arr: np.ndarray) -> np.ndarray:
        return np.clip(arr / (np.percentile(arr, 96) + 1e-9), 0.0, 1.6).astype(np.float32)

    S = {k: ema(norm(v), 0.22) for k, v in out.items()}
    S["rms"] = ema(norm(rms), 0.28)
    fl = norm(flux)
    nov = np.clip(fl - ema(fl, 1.4) * 1.12, 0.0, None)
    thr = np.percentile(nov, 92) + 1e-6
    onsets, last = [], -999
    for i in range(1, total_frames - 1):
        if nov[i] > thr and nov[i] >= nov[i - 1] and nov[i] >= nov[i + 1] and i - last >= 8:
            onsets.append(i)
            last = i
    on = np.zeros(total_frames, np.float32)
    for f in onsets:
        on[f] = min(nov[f] / (thr * 2.4), 1.0)
    env = np.zeros(total_frames, np.float32)
    acc = 0.0
    dec = math.exp(-DT / 0.34)
    for i in range(total_frames):
        acc = max(float(on[i]), acc * dec)
        env[i] = acc
    S["onset"] = env
    S["onset_raw"] = on
    low_n = norm(out["low"])
    S["low_nov"] = np.clip(ema(low_n, 0.14) - ema(low_n, 2.2), 0.0, None)
    S["onset_frames"] = onsets
    return S


def build_events(S: dict, seed: int, scene_sec: float = 75.0) -> dict:
    """사운드 스펙트럼 피크에서 장면별 충격/균열 이벤트 프레임을 추출."""
    rng = np.random.default_rng(seed)
    total_f = len(S["onset"])

    def peaks_in(sig: np.ndarray, t0: float, t1: float, min_gap_s: float, pct: float) -> list[int]:
        f0, f1 = max(0, int(t0 * FPS)), min(total_f, int(t1 * FPS))
        if f1 - f0 < 10:
            return []
        seg = sig[f0:f1]
        thr = np.percentile(seg, pct)
        out_p, last = [], -10 ** 9
        gap = max(4.0, min_gap_s * FPS)
        for i in range(1, len(seg) - 1):
            if seg[i] > thr and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1] and (i - last) >= gap:
                out_p.append(f0 + i)
                last = i
                gap = max(4.0, min_gap_s * FPS * rng.uniform(0.75, 1.45))
        return out_p

    scale = max(0.2, scene_sec / 75.0)
    return {
        "act_shocks": [
            peaks_in(S["low_nov"] + 0.6 * S["onset"], i * scene_sec + 1.5 * scale, (i + 1) * scene_sec - 1.5 * scale, 3.2 * scale, 80)
            for i in range(4)
        ]
    }


# --------------------------------------------------------------------------------------
# 1. StructuralDreamCA — 구조 결 기반 증식 · 불규칙 연쇄 붕괴 · 변이 재생성 셀룰러 오토마타
# --------------------------------------------------------------------------------------
class ConstructiveField:
    """A lattice of descendants with owned RGB state, never a source-image reveal.

    Coarse births require a living Moore neighbour. Descendants inherit colour
    and orientation. GA uses population selection/crossover/mutation; CA uses
    a target-conditioned local colour rule. Fine RGB genes are then refined in
    persistent state. Completion is measured, and destruction transports that
    generated state using a forward splat (including its geometry).
    """
    tile = 12
    method = "CA"

    def __init__(self, target: np.ndarray, profile: dict, seed: int):
        self.profile, self.seed = profile, seed
        self.rng = np.random.default_rng(seed)
        self.h, self.w = target.shape[:2]
        self.nh, self.nw = self.h // self.tile, self.w // self.tile
        self.target = T(target)
        self.goal = cv2.resize(target, (self.nw, self.nh), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(self.goal, cv2.COLOR_RGB2GRAY)
        gx, gy = cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)
        mag = np.hypot(gx, gy)
        self.edge = np.clip(mag / (np.percentile(mag, 90) + 1e-6), 0, 1)
        norm = mag + 1e-5
        self.goal_genes = np.concatenate([self.goal, (-gy/norm)[...,None], (gx/norm)[...,None]], -1)
        yy, xx = np.mgrid[:self.nh, :self.nw]
        self.ids = np.arange(self.nh*self.nw).reshape(self.nh, self.nw)
        self.nx, self.ny = xx.astype(np.float32), yy.astype(np.float32)
        self.phase = self.rng.uniform(0, 2*np.pi, (self.nh, self.nw)).astype(np.float32)
        self.records, self.logs = [], []
        self.current_cycle = -1
        self.generation = 0
        self.last_snapshot = {}
        # Render geometry is independent of the target image.
        py, px = torch.meshgrid(torch.arange(self.h, device=DEV), torch.arange(self.w, device=DEV), indexing="ij")
        self.px, self.py = px.float(), py.float()
        self.local_x = ((self.px % self.tile) + .5) / self.tile - .5
        self.local_y = ((self.py % self.tile) + .5) / self.tile - .5
        self.node_index = ((py//self.tile)*self.nw + px//self.tile).long()
        self.centre_x = (px//self.tile).float()*self.tile + self.tile*.5
        self.centre_y = (py//self.tile).float()*self.tile + self.tile*.5
        self.detail, self.frozen = None, None

    @staticmethod
    def shifted(a, dy, dx):
        out = np.roll(a, (dy, dx), axis=(0, 1)).copy()
        if dy > 0: out[:dy] = 0
        if dy < 0: out[dy:] = 0
        if dx > 0: out[:, :dx] = 0
        if dx < 0: out[:, dx:] = 0
        return out

    def reset(self, cycle_idx, duration):
        self.current_cycle, self.duration = cycle_idx, float(duration)
        self.alive = np.zeros((self.nh, self.nw), bool)
        self.born = np.full((self.nh, self.nw), -100., np.float32)
        self.parent = np.full((self.nh, self.nw), -1, np.int32)
        self.genes = np.zeros((self.nh, self.nw, 5), np.float32)
        cx = int(self.nw*self.rng.uniform(.38, .62))
        cy = int(self.nh*self.rng.uniform(.35, .65))
        self.seed_xy = (cx, cy)
        self.alive[cy,cx], self.born[cy,cx] = True, 0.
        self.genes[cy,cx,:3] = self.profile["seed_rgb"]
        self.genes[cy,cx,3:] = (1., 0.)
        self.population = np.repeat(self.genes[None], 5, axis=0)
        self.work_credit = 0.
        self.detail = self.frozen = None
        self.refine_t = self.complete_t = self.break_t = None
        self.fine_steps = self.local_steps = self.orphans = 0
        self.generation = 0
        self.mae = self.psnr = None
        self.stage = "seed"
        self.record = dict(cycle=cycle_idx, method=self.method, initial_count=1,
                           seed_xy=[cx,cy], completion=None, orphan_births=0,
                           target_pixels=self.w*self.h, coarse_nodes=self.nw*self.nh,
                           collapse_started=False, ended_empty=False, samples=[])
        self.records.append(self.record)
        self.gpu_rng = torch.Generator(device=DEV).manual_seed(self.seed + cycle_idx*7103)

    def _birth_step(self, elapsed, progress):
        # All parents are taken from the PREVIOUS state. No wraparound births.
        old = self.alive.copy()
        eligible = np.zeros_like(old)
        count = np.zeros(old.shape, np.float32)
        best = np.full(old.shape, -1., np.float32)
        parent_ids = np.full(old.shape, -1, np.int32)
        inherited = np.zeros_like(self.genes)
        tx, ty = self.goal_genes[...,3], self.goal_genes[...,4]
        for dy, dx in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
            nb = self.shifted(old, dy, dx)
            count += nb
            alignment = np.abs(tx*dx + ty*dy) / math.hypot(dx,dy)
            score = self.rng.random(old.shape).astype(np.float32) + .55*alignment
            use = nb & (score > best)
            source = self.shifted(self.genes, dy, dx)
            inherited[use] = source[use]
            parent_ids[use] = self.shifted(self.ids, dy, dx)[use]
            best[use] = score[use]
            eligible |= nb
        frontier = eligible & ~old
        # Structural edges branch first; later density comes ONLY from neighbours.
        chance = .13 + .56*self.edge + .055*np.minimum(count, 3)
        if self.method == "CA": chance += .06
        if progress > .24: chance += .32
        born = frontier & (self.rng.random(old.shape) < np.clip(chance, 0, .99))
        if not np.any(born): return
        parents = parent_ids[born]
        self.orphans += int(np.count_nonzero(~old.ravel()[parents]))
        self.parent[born] = parents
        self.alive[born] = True
        self.born[born] = elapsed
        self.genes[born] = inherited[born]
        if self.method == "GA":
            for k in range(5):
                self.population[k,born] = inherited[born] + self.rng.normal(0, .07, (int(born.sum()),self.genes.shape[-1]))
        self.local_steps += 1

    def _colour_generation(self):
        if self.method == "GA":
            pop = self.population
            # Elitism + RGB/orientation chromosomes crossed with another elite.
            err = ((pop[...,:3]-self.goal[None])**2).mean(-1)
            err += .018*((pop[...,3:]-self.goal_genes[None,...,3:])**2).mean(-1)
            rank = np.argsort(err, axis=0)
            elite = np.take_along_axis(pop, rank[:2,...,None], axis=0)
            children = [elite[0]]
            for k in range(4):
                mix = self.rng.uniform(.15,.85, (*self.alive.shape,1)).astype(np.float32)
                child = elite[0]*mix + elite[1]*(1-mix)
                residual = self.goal_genes-child
                # Target-guided mutation (memetic GA), evaluated before acceptance.
                gain = self.rng.uniform(.16,.52, (*self.alive.shape,1)).astype(np.float32)
                noise = self.rng.normal(size=child.shape).astype(np.float32)
                child += gain*residual + noise*(np.abs(residual)*.18 + .003)
                child[...,:3] = np.clip(child[...,:3],0,1)
                children.append(child)
            candidates = np.stack(children)
            fit = ((candidates[...,:3]-self.goal[None])**2).mean(-1)
            fit += .018*((candidates[...,3:]-self.goal_genes[None,...,3:])**2).mean(-1)
            ranks = np.argsort(fit, axis=0)
            self.population = np.take_along_axis(candidates, ranks[...,None], axis=0)
            self.genes[self.alive] = self.population[0,self.alive]
        else:
            # Continuous, target-conditioned cellular automaton: inherited colour,
            # neighbour coupling, and a local error correction at each live cell.
            rgb = self.genes[...,:3]
            weights = cv2.blur(self.alive.astype(np.float32),(3,3))[...,None]
            neighbour = cv2.blur(rgb*self.alive[...,None],(3,3)) / np.maximum(weights,1e-5)
            proposed = rgb + .36*(self.goal-rgb) + .045*(neighbour-rgb)
            rgb[self.alive] = np.clip(proposed[self.alive],0,1)
        self.generation += 1

    def coarse_tensor(self):
        return F.interpolate(T(self.genes[...,:3]), size=(self.h,self.w), mode="nearest")

    def _refine(self, elapsed):
        if self.detail is None:
            self.detail = self.coarse_tensor().clone()
            self.refine_t = elapsed
        live = self.expand(self.alive.astype(np.float32))[None,None]
        # Independent pixel descendants inherit the existing coarse-cell RGB.
        # Target data is used only in mutation/rule evaluation, never compositing.
        if self.method == "GA":
            residual = self.target-self.detail
            gain = torch.rand((1,1,self.nh,self.nw),device=DEV,generator=self.gpu_rng)*.24+.24
            gain = F.interpolate(gain,size=(self.h,self.w),mode="nearest")
            noise = torch.randn(self.detail.shape,device=DEV,generator=self.gpu_rng)
            cross = .9*self.detail + .1*torch.roll(self.detail,1,dims=3)
            candidate = cross + gain*(self.target-cross) + noise*(residual.abs()*.06 + .0005)
            best_error = ((self.detail-self.target)**2).sum(1,keepdim=True)
            new_error = ((candidate-self.target)**2).sum(1,keepdim=True)
            accepted = (new_error < best_error) & (live > 0)
            self.detail = torch.where(accepted,candidate.clamp(0,1),self.detail)
            candidate2 = self.detail + gain*(self.target-self.detail) + noise*(residual.abs()*.04+.0003)
            accepted2 = (((candidate2-self.target)**2).sum(1,keepdim=True) <
                         ((self.detail-self.target)**2).sum(1,keepdim=True)) & (live > 0)
            self.detail = torch.where(accepted2,candidate2.clamp(0,1),self.detail)
        else:
            residual = self.detail-self.target
            nb = F.avg_pool2d(F.pad(residual,(1,1,1,1),mode="replicate"),3,stride=1)
            self.detail = (self.detail + live*(-.34*residual + .10*(nb-residual))).clamp(0,1)
        self.fine_steps += 1
        error = self.detail-self.target
        self.mae = float(error.abs().mean())
        mse = float((error**2).mean())
        self.psnr = -10*math.log10(max(mse,1e-12))

    def step(self, elapsed, cycle_idx, duration, onset=0.):
        if cycle_idx != self.current_cycle: self.reset(cycle_idx,duration)
        self.elapsed = elapsed
        p = elapsed/duration
        seed_end = .055*duration
        if self.complete_t is None:
            if elapsed < seed_end:
                self.stage = "seed"
            else:
                self.stage = "growth"
                mood = self.profile["mood_style"]
                tempo = 1.
                if mood == "dark_horror": tempo = .83 + .38*(math.sin(elapsed*13)>0) + .12*onset
                elif mood == "bright_happy": tempo = 1.06 + .12*math.sin(elapsed*6)**2
                elif mood == "dark_calm": tempo = .96 + .08*math.sin(elapsed*2)
                budget = 120 if p < .26 else 185
                self.work_credit += DT * (budget/(duration*.46)) * tempo
                for _ in range(int(self.work_credit)):
                    self._birth_step(elapsed,p)
                self.work_credit %= 1.
                self._colour_generation()
                # Keep the dots legible before allowing descendants to resolve detail.
                coverage = float(self.alive.mean())
                if coverage > .985 and p >= .43:
                    self.stage = "refinement"
                    self._refine(elapsed)
                if (self.detail is not None and self.alive.all() and self.fine_steps >= 22
                        and self.mae < .007 and self.psnr > 38):
                    self.complete_t = elapsed
                    hold = self.profile["hold_fraction"]*duration
                    self.break_t = self.complete_t + hold
                    if self.break_t > duration*.82:
                        raise RuntimeError(f"{self.method}: convergence too late ({elapsed:.2f}s); no forced image completion")
                    self.record["completion"] = dict(seconds=round(elapsed,3), nodes=int(self.alive.sum()),
                        mae=round(self.mae,7), psnr_db=round(self.psnr,3), generations=self.generation,
                        fine_steps=self.fine_steps, local_steps=self.local_steps)
                    self.record["orphan_births"] = self.orphans
                    self.frozen = self.detail.detach().clone()
                    self._prepare_collapse()
            if p > .70 and self.complete_t is None:
                raise RuntimeError(f"{self.method} failed to converge: coverage={self.alive.mean():.3f}, MAE={self.mae}, PSNR={self.psnr}")
        if self.complete_t is not None:
            if elapsed < self.break_t:
                self.stage = "complete"
            elif elapsed < duration*.98:
                self.stage = "collapse"
                self.record["collapse_started"] = True
            else:
                self.stage = "empty"
                self.record["ended_empty"] = True
        if int(round(elapsed*FPS)) % 12 == 0:
            self.record["samples"].append(dict(seconds=round(elapsed,3),stage=self.stage,
                active_nodes=int(self.alive.sum()),mae=None if self.mae is None else round(self.mae,6)))
        self.last_snapshot = dict(method=self.method,stage=self.stage,active_nodes=int(self.alive.sum()),
            generation=self.generation,mae=self.mae,psnr=self.psnr,cycle=cycle_idx)

    def expand(self, a):
        return F.interpolate(torch.as_tensor(a,device=DEV,dtype=torch.float32)[None,None],
                             size=(self.h,self.w),mode="nearest")[0,0]

    def _prepare_collapse(self):
        mood = self.profile["mood_style"]
        nx = (self.nx+.5)/self.nw-.5
        ny = (self.ny+.5)/self.nh-.5
        noise = self.rng.uniform(0,1,nx.shape).astype(np.float32)
        # A travelling fracture with cell-level delays. RGB and geometry travel together.
        if mood == "dark_horror":
            delay = .22*(1-(self.ny/self.nh)) + noise*.08
            vx = self.rng.normal(0,90,nx.shape); vy = 140 + noise*130
            gravity = 950.
        elif mood == "bright_happy":
            delay = .14*(nx**2+ny**2) + noise*.13
            vx = nx*600 + self.rng.normal(0,45,nx.shape); vy = -100-noise*100
            gravity = -110.
        elif mood == "dark_calm":
            delay = .22*(.5+.5*np.sin(nx*7+ny*5)) + noise*.08
            vx = 36*np.sin(ny*8)+self.rng.normal(0,12,nx.shape); vy = 55+noise*40
            gravity = 150.
        else:
            delay = noise*.15 + .12*(nx+.5)
            vx = -ny*240+self.rng.normal(0,25,nx.shape); vy = nx*100-75-noise*45
            gravity = -80.
        self.fall_delay = self.expand(delay)
        self.fall_vx, self.fall_vy = self.expand(vx), self.expand(vy)
        self.fall_spin = self.expand(self.rng.normal(0,.9 if self.method=="GA" else .35,nx.shape))
        self.gravity = gravity

    def _render_collapse(self, canvas):
        span = self.duration*.992-self.break_t
        q = (self.elapsed-self.break_t)/span
        age = ((q-self.fall_delay)/(1-self.fall_delay)).clamp(0,1)
        # Forward mapping of owned source texels, not moving texture in a fixed hole.
        seconds = age*2.0
        shrink = (1-.72*age).clamp(.25,1)
        angle = self.fall_spin*seconds
        lx, ly = self.local_x*self.tile, self.local_y*self.tile
        rx = (lx*torch.cos(angle)-ly*torch.sin(angle))*shrink
        ry = (lx*torch.sin(angle)+ly*torch.cos(angle))*shrink
        xx = self.centre_x + rx + self.fall_vx*seconds
        yy = self.centre_y + ry + self.fall_vy*seconds + .5*self.gravity*seconds**2
        xi, yi = (xx-.5).round().long(), (yy-.5).round().long()
        valid = (xi>=0)&(xi<self.w)&(yi>=0)&(yi<self.h)&(age<.985)
        if self.method == "GA":
            radius = .73-.20*age
            valid &= self.local_x**2+self.local_y**2 < radius**2
        # The final loss is confined to each moving descendant, after displacement.
        alpha = (1-((age-.72)/.265).clamp(0,1))
        idx = (yi[valid]*self.w+xi[valid]).reshape(-1)
        weights = alpha[valid].reshape(-1)
        accum = torch.zeros((4,self.h*self.w),device=DEV)
        colours = self.frozen[0,:,valid] * weights[None]
        accum[:3].index_add_(1,idx,colours)
        accum[3].index_add_(0,idx,weights)
        coverage = accum[3:4].clamp(0,1)
        rgb = accum[:3]/accum[3:4].clamp(min=1e-6)
        return (canvas.reshape(3,-1)*(1-coverage)+rgb*coverage).view(1,3,self.h,self.w)

    def render(self, canvas):
        if self.stage == "empty": return canvas.clone()
        if self.stage == "collapse": return self._render_collapse(canvas)
        if self.stage == "complete": return self.frozen.clone()
        age_np = np.maximum(0,self.elapsed-self.born)
        age = self.expand(age_np)
        live = self.expand(self.alive.astype(np.float32))
        phase = self.expand(self.phase)
        mood = self.profile["mood_style"]
        wobble = {"dark_horror":.19,"bright_happy":.13,"dark_calm":.045,"vivid_mystery":.095}[mood]
        freq = {"dark_horror":12.,"bright_happy":6.,"dark_calm":1.8,"vivid_mystery":3.2}[mood]
        if self.detail is None:
            settled = 0.
            rgb = self.coarse_tensor()
        else:
            settled = ss(0,.58,self.elapsed-self.refine_t)
            rgb = self.detail
        dx = self.local_x - wobble*torch.sin(phase+self.elapsed*freq)*(1-settled)
        dy = self.local_y - wobble*torch.cos(phase*.73+self.elapsed*freq*.8)*(1-settled)
        parent_ids = np.maximum(self.parent,0)
        parent_dx = parent_ids%self.nw-self.nx
        parent_dy = parent_ids//self.nw-self.ny
        lineage = (self.parent>=0).astype(np.float32)
        bud = torch.exp(-age*9)*(1-settled)*.30
        dx -= self.expand(parent_dx*lineage)*bud
        dy -= self.expand(parent_dy*lineage)*bud
        r = (.16+.24*(1-torch.exp(-age*7)))*(1-settled)+.73*settled
        if self.method == "GA":
            # Inherited and selected orientation changes the actual point geometry.
            tx,ty = self.expand(self.genes[...,3]),self.expand(self.genes[...,4])
            norm = torch.sqrt(tx*tx+ty*ty).clamp(min=1e-5)
            tx,ty = tx/norm,ty/norm
            elongation = 1.+.30*(1-settled)
            shape = torch.sqrt(((dx*tx+dy*ty)/elongation)**2+((-dx*ty+dy*tx)*elongation)**2)
            alpha = ((r-shape)*self.tile*1.3+.5).clamp(0,1)*live
        else:
            shape = torch.maximum(dx.abs(),dy.abs())
            r = r*(1-settled)+.51*settled
            alpha = ((r-shape)*self.tile+.5).clamp(0,1)*live
        # A birth glints briefly; colour subsequently comes from the descendant's genes.
        accent = torch.as_tensor(self.profile["seed_rgb"],device=DEV).view(1,3,1,1)
        glint = torch.exp(-age*9)*live*(1-settled)*.27
        rgb = rgb + accent*glint[None,None]
        out = canvas*(1-alpha[None,None])+rgb*alpha[None,None]
        # Single initial point is made readable by a halo, without any extra seeds.
        if self.stage == "seed":
            cx,cy = self.seed_xy
            dist = ((self.px-(cx+.5)*self.tile)**2+(self.py-(cy+.5)*self.tile)**2)
            glow = torch.exp(-dist/80.)*.65
            out = out+accent*glow[None,None]
        return out.clamp(0,1)


class DreamConstructiveField(ConstructiveField):
    """Build the reference's space from one seed, then keep rebuilding its matter.

    The image pyramid is a fitness/rule target only. Visible colour is inherited
    persistent state. GA, CA and story motion all work on that same owned state.
    """
    def __init__(self,target,profile,seed):
        super().__init__(target,profile,seed)
        self.final_goal=self.goal.copy()
        self.structural_edge=self.edge.copy()
        self.pyramid=[T(cv2.GaussianBlur(target,(0,0),s)) for s in (22.,10.,3.)]+[self.target]
        self.u=(self.px+.5)/self.w
        self.v=(self.py+.5)/self.h
        self.base_grid=torch.stack([self.u*2-1,self.v*2-1],-1)[None]
        noise=np.random.default_rng(seed+39).random((self.h,self.w)).astype(np.float32)
        self.dust=torch.as_tensor(noise,device=DEV)
        low=cv2.resize(self.rng.random((9,15)).astype(np.float32),(self.nw,self.nh),interpolation=cv2.INTER_CUBIC)
        self.region=self.expand(low)
        # Rigid irregular regions, not spatial sine waves bending architecture.
        gy,gx=np.mgrid[:self.nh,:self.nw]
        sites=np.array([(self.rng.uniform(x,x+1)*self.nw/12,
                         self.rng.uniform(y,y+1)*self.nh/7)
                        for y in range(7) for x in range(12)],np.float32)
        labels=np.argmin((gx[...,None]-sites[:,0])**2+(gy[...,None]-sites[:,1])**2,axis=2)
        self.patch_labels=labels
        values=self.rng.uniform(-1,1,(len(sites),3)).astype(np.float32)
        self.patch_x=self.expand(values[labels,0])
        self.patch_y=self.expand(values[labels,1])
        self.patch_phase=self.expand((values[labels,2]+1)*.5)

    def _emotion_controls(self):
        vec=list(self.profile.get('emotion_vector',[0.,.4,.4,0.]))
        vec=(vec+[0.]*4)[:4]
        return dict(intensity=float(np.clip(self.profile.get('intensity',.55),0,1)),
            pleasant=float(np.clip(vec[0],-1,1)),attention=float(np.clip((vec[1]+1)/2,0,1)),
            sensitivity=float(np.clip((vec[2]+1)/2,0,1)),aptitude=float(np.clip((vec[3]+1)/2,0,1)))

    def _story(self,key,default=0.):
        return getattr(self,'story_state',{}).get(key,default)

    def reset(self,cycle_idx,duration):
        if duration<30:raise ValueError('Use at least 60 seconds per act')
        super().reset(cycle_idx,duration)
        self.previous_live=self.alive.copy()
        self.target_weight=1.
        self.record['source_guided_from_first_birth']=True
        self.record['construction']='persistent multiscale RGB descendants'
        self.activity=np.zeros_like(self.edge)
        self.activity[self.alive]=1.
        self.refractory=np.zeros_like(self.edge)
        self.working_goal=self.pyramid[0]
        self.elapsed=0.
        self.last_onset=0.
        self.record['emotion_controls']=self._emotion_controls()

    def _update_detail(self,p):
        if self.detail is None:
            self.detail=self.coarse_tensor().clone()
            self.refine_t=self.elapsed
        new=self.alive & ~self.previous_live
        if new.any():
            self.detail=torch.where(self.expand(new.astype(np.float32))[None,None]>0,
                                    self.coarse_tensor(),self.detail)
        self.previous_live=self.alive.copy()
        # Coarse-to-fine target changes the optimization problem, never the display.
        level=float(np.interp(p,[.02,.26,.53,.76],[0.,1.,2.,3.]))
        lo=min(2,int(level));a=level-lo
        self.working_goal=self.pyramid[lo]*(1-a)+self.pyramid[lo+1]*a
        live=self.expand(self.alive.astype(np.float32))[None,None]
        if self.method=='GA':
            residual=self.working_goal-self.detail
            mutation=torch.randn(self.detail.shape,device=DEV,generator=self.gpu_rng)
            emo=self._emotion_controls()
            strength=.010*(1.12-.24*emo['aptitude'])*(1-ss(.5,.80,p))+.00025
            gain=.15+.055*emo['attention']
            child=self.detail+gain*residual+mutation*(residual.abs()*.10+strength)
            error=(self.detail-self.working_goal).square().sum(1,keepdim=True)
            fit=(child-self.working_goal).square().sum(1,keepdim=True)
            self.detail=torch.where((fit<error)&(live>0),child.clamp(0,1),self.detail)
        else:
            residual=self.detail-self.working_goal
            neighbour=F.avg_pool2d(F.pad(residual,(1,1,1,1),mode='replicate'),3,stride=1)
            gain=.22+.045*self._emotion_controls()['sensitivity']
            self.detail=(self.detail+live*(-gain*residual+.10*(neighbour-residual))).clamp(0,1)
        self.fine_steps+=1
        error=self.detail-self.target
        self.mae=float(error.abs().mean())
        self.psnr=-10*math.log10(max(float(error.square().mean()),1e-12))

    def step(self,elapsed,cycle_idx,duration,onset=0.):
        if cycle_idx!=self.current_cycle:self.reset(cycle_idx,duration)
        self.elapsed,self.last_onset=elapsed,onset
        p=elapsed/duration
        if self.complete_t is None:
            if p<.016:
                self.stage='seed'
            else:
                self.stage='growth' if not self.alive.all() else 'reconstruction'
                self.edge=self.structural_edge
                # At ~7s the space is present but coarse, porous and constantly rebuilt.
                emo=self._emotion_controls()
                tempo=.82+.28*emo['intensity']+.10*emo['sensitivity']+.08*self._story('tension',.5)
                if self.profile['mood_style']=='dark_horror':tempo*=1.05
                self.work_credit+=DT*150/(duration*.20)*tempo
                for _ in range(int(self.work_credit)):
                    self._birth_step(elapsed,p)
                self.work_credit%=1
                self._colour_generation()
                if self.method=='CA' and self.generation%3==0:
                    firing=(self.activity>.32).astype(np.float32)
                    neighbour=cv2.filter2D(firing,-1,np.ones((3,3),np.float32),borderType=cv2.BORDER_CONSTANT)-firing
                    excited=(neighbour>=1)&(self.refractory<=0)&self.alive
                    self.activity=np.where(excited,1.,self.activity*.74).astype(np.float32)
                    self.refractory=np.maximum(self.refractory-1,0)
                    self.refractory[excited]=int(round(24-10*emo['sensitivity']))
                    if self.generation%90==0:
                        candidates=np.flatnonzero(self.alive & (self.structural_edge>.4))
                        if len(candidates):
                            point=int(self.rng.choice(candidates));self.activity.ravel()[point]=1.
                self._update_detail(p)
                if p>=.83 and self.alive.all() and self.mae<.007 and self.psnr>38:
                    self.complete_t=elapsed
                    self.break_t=elapsed+duration*.030
                    self.record['completion']=dict(seconds=round(elapsed,3),nodes=int(self.alive.sum()),
                        mae=round(self.mae,7),psnr_db=round(self.psnr,3),generations=self.generation,
                        fine_steps=self.fine_steps,local_steps=self.local_steps)
                    self.record['orphan_births']=self.orphans
                    self.frozen=self.detail.detach().clone()
                    self._prepare_collapse()
            if p>.875 and self.complete_t is None:
                raise RuntimeError(f'{self.method} did not converge: MAE={self.mae}, PSNR={self.psnr}')
        if self.complete_t is not None:
            self.stage='complete' if elapsed<self.break_t else ('collapse' if p<.995 else 'handoff')
            if self.stage=='collapse':self.record['collapse_started']=True
            if self.stage=='handoff':self.record['ended_recycled']=True
        if int(round(elapsed*FPS))%60==0:
            self.record['samples'].append(dict(seconds=round(elapsed,3),stage=self.stage,
                active_nodes=int(self.alive.sum()),target_weight=1.,mae=self.mae,
                story_beat=self._story('beat','mood'),tension=self._story('tension',.5)))
        self.last_snapshot=dict(method=self.method,stage=self.stage,active_nodes=int(self.alive.sum()),
            generation=self.generation,mae=self.mae,psnr=self.psnr,cycle=cycle_idx,target_weight=1.,
            story_beat=self._story('beat','mood'),story_tension=self._story('tension',.5),
            story_opening=self._story('opening'),story_retreat=self._story('retreat'),
            emotion_intensity=self._emotion_controls()['intensity'])

    def _story_flow(self,p):
        emo=self._emotion_controls()
        speed=self.profile.get('params',{}).get('speed',1.)
        t=self.elapsed*(.85+.25*speed)
        envelope=ss(.02,.16,p)*(1-ss(.67,.825,p))
        u,v=self.u,self.v
        mood=self.profile['mood_style']
        if mood=='dark_horror':
            # Visible forward rush, lateral recoil, and compression of the passage.
            rush=.085*math.sin(t*.86)+.027*math.sin(t*3.2)
            dx=(u-.57)*rush+.026*math.sin(t*1.7)+.025*torch.sin(v*11-t*1.6)
            dy=(v-.52)*rush+.014*math.sin(t*3.4)+.016*torch.sin(u*13+t)
        elif mood=='bright_happy':
            dx=(u-.5)*(.055*math.sin(t*.45))+.018*torch.sin(v*9-t*.65)
            dy=-.025*math.sin(t*.35)+.016*torch.sin(u*9+t*.5)
        elif mood=='dark_calm':
            dx=torch.tanh((u-.5)*8)*.027*math.sin(t*.21)+.012*torch.sin(v*8-t*.33)
            dy=.018*math.sin(t*.23)+.012*torch.sin(u*7+t*.2)
        else:
            dx=.026*torch.sin(v*11+t*.61)+.016*torch.sin((u+v)*17-t*.87)
            dy=.025*torch.sin(u*9-t*.48)+.013*math.sin(t*.71)
        if self.method=='GA':
            dx+=.010*torch.sin(v*29+u*11+t*1.3)
            dy+=.010*torch.sin(u*25-v*8-t*.9)
        else:
            # Regionally propagated stepped deformations, not a global smooth warp.
            activity=self.expand(self.activity)
            dx=(torch.round(dx*self.w/22)*22/self.w)+.025*activity*torch.sin(v*20-t*1.9)
            dy=(torch.round(dy*self.h/18)*18/self.h)+.024*activity*torch.cos(u*18+t*1.6)
        tension=self._story('tension',.5)
        motion=(.75+.45*emo['intensity'])*(.75+.40*tension)*(1.12-.24*emo['aptitude'])
        motion*=1-.91*self._story('pause')
        dx*=motion;dy*=motion
        travel=self._story('travel')*(.035+.06*abs(self.profile.get('loco_vel',.2)))
        opening=self._story('opening')*(.035+.10*self.profile.get('aperture_amp',0.))
        retreat=self._story('retreat')*.075
        dx+=(u-.5)*(-travel-opening+retreat)
        dy+=(v-.48)*(-travel-opening+retreat)
        shake=.006*emo['sensitivity']*tension*(1-self._story('pause'))
        dx+=shake*torch.sin(v*18+t*(1.3+emo['sensitivity']))
        dy+=shake*.65*torch.sin(u*17-t*1.8)
        # Restore v10 irregular motion; retain v11 camera continuity into completion.
        cam_x,cam_y=self._camera_flow()
        return dx*envelope+cam_x,dy*envelope+cam_y,envelope

    def _camera_flow(self):
        t=self.elapsed
        fx,fy=self._story('focal_x',.5),self._story('focal_y',.5)
        # Small continuous camera drift, never a character's running gait.
        zoom=1.026+.00025*t+.014*self._story('tension',.5)-.012*self._story('opening')-.009*self._story('retreat')
        pan_x=.003*math.sin(t*.13)+.0015*math.sin(t*.31)
        pan_y=.0025*math.sin(t*.09)-.003*self._story('opening')+.003*self._story('retreat')
        return (self.u-fx)*(1/zoom-1)+pan_x,(self.v-fy)*(1/zoom-1)+pan_y

    def _living_light(self,rgb):
        t=self.elapsed;emo=self._emotion_controls()
        sweep=torch.exp(-((self.u-(.5+.42*math.sin(t*.19)))/.16).square())
        amount=.008+.012*emo['intensity']+.008*self._story('light')
        return rgb*(1+amount*(sweep[None,None]-.35)+.012*self.last_onset)

    def _render_complete(self):
        dx,dy=self._camera_flow()
        grid=self.base_grid+torch.stack([dx*2,dy*2],-1)[None]
        out=F.grid_sample(self.frozen,grid,mode='bilinear',padding_mode='border',align_corners=False)
        return self._living_light(out).clamp(0,1)

    def render(self,canvas):
        if self.stage=='empty':return canvas.clone()
        if self.stage=='complete':return self._render_complete()
        if self.stage in ('collapse','handoff'):return self._render_collapse(canvas)
        if self.stage=='seed':return super().render(canvas)
        p=self.elapsed/self.duration
        dx,dy,envelope=self._story_flow(p)
        live=self.expand(self.alive.astype(np.float32))
        age=(self.elapsed-self.expand(self.born)).clamp(min=0)
        density=.78+.22*ss(.25,.825,p)
        grain=(self.dust<density).float()
        # Fine particle matter remains visible while the architectural shapes can read.
        if self.method=='GA':
            tx,ty=self.expand(self.genes[...,3]),self.expand(self.genes[...,4])
            streak=.64+.36*torch.sin((self.px*tx+self.py*ty)*.69+self.region*12).square()
            material=grain*streak
            colour=self.detail
        else:
            activity=self.expand(self.activity)
            cell=30
            gap_x=((self.px%cell)+.5)/cell-.5
            gap_y=((self.py%cell)+.5)/cell-.5
            cell_gap=(torch.maximum(gap_x.abs(),gap_y.abs())<.46).float()
            material=grain*(.68+.32*activity)*(cell_gap*(1-ss(.45,.80,p))+ss(.45,.80,p))
            cells=F.interpolate(F.avg_pool2d(self.detail,cell,cell),size=(self.h,self.w),mode='nearest')
            fine=ss(.42,.80,p)
            colour=cells*(1-fine)+self.detail*fine
        settle=ss(.65,.825,p)
        material=material*(1-settle)+settle
        alpha=live*(1-torch.exp(-age*4))*material
        # Premultiplied RGBA moves together: no stationary source-shaped reveal mask.
        rgba=torch.cat([colour*alpha[None,None],alpha[None,None]],1)
        grid=self.base_grid+torch.stack([dx*2,dy*2],-1)[None]
        moving=F.grid_sample(rgba,grid,mode='bilinear',padding_mode='zeros',align_corners=False)
        rgb,a=moving[:,:3],moving[:,3:]
        mood=self.profile['mood_style'];t=self.elapsed
        if mood=='dark_horror':
            contrast=1+.27*envelope
            gain=1-envelope*.17+envelope*.16*math.sin(t*1.9)**8
            tint=torch.tensor([1+.10*math.sin(t*.6),.98,1.08],device=DEV).view(1,3,1,1)
        elif mood=='bright_happy':
            contrast=1+.08*envelope;gain=1+envelope*.08*math.sin(t*.5)
            tint=torch.tensor([1.08,1.02,.94],device=DEV).view(1,3,1,1)
        elif mood=='dark_calm':
            contrast=1-.13*envelope;gain=1-envelope*(.10+.06*math.sin(t*.25))
            tint=torch.tensor([.94,.99,1.05],device=DEV).view(1,3,1,1)
        else:
            contrast=1+envelope*.10*math.sin(t*.51);gain=1+envelope*.12*math.sin(t*.66)
            tint=torch.tensor([1.03,1-.05*math.sin(t*.39),1.03],device=DEV).view(1,3,1,1)
        emo=self._emotion_controls()
        tension=self._story('tension',.5)
        contrast=1+(contrast-1)*(.7+.6*emo['intensity'])
        warmth=.65*self._story('warmth')+.25*emo['pleasant']+.10*self.profile.get('warm_bias',0.)
        tint=tint*torch.tensor([1+.07*warmth,1.,1-.07*warmth],device=DEV).view(1,3,1,1)
        radius=.33-.16*emo['attention']
        fx,fy=self._story('focal_x',.5),self._story('focal_y',.5)
        focus=torch.exp(-(((self.u-fx)/radius)**2+((self.v-fy)/(radius*.85))**2))
        exposure=envelope*self._story('focus')*((.11+.05*emo['attention'])*focus-.055*(1-focus))
        exposure+=envelope*.05*self._story('light')*focus
        pulse=self.profile.get('pulse_amp',.2)*max(0.,tension-.7)*math.sin(t*2.7)**8
        gain*=1+envelope*.35*pulse
        grey=lum(rgb)
        rgb=grey+(rgb-grey)*(1+.4*(contrast-1))
        # Contrast acts on luminance as well as chroma, in premultiplied space.
        rgb=(rgb-.28*a)*contrast+.28*a
        rgb=(rgb*gain*(1+(tint-1)*envelope)*(1+exposure[None,None])).clamp(min=0)
        return (canvas*(1-a)+self._living_light(rgb)).clamp(0,1)

    def _prepare_collapse(self):
        # Weak zones are connected through a local weighted propagation process.
        # Their varying arrival times make architecture loosen before it disperses.
        import heapq
        terrain=cv2.GaussianBlur(self.rng.random(self.alive.shape).astype(np.float32),(0,0),2.2)
        terrain=(terrain-terrain.min())/(np.ptp(terrain)+1e-6)
        emo=self._emotion_controls()
        resistance=.4+(1.+.6*emo['sensitivity'])*terrain+(.4+.8*emo['aptitude'])*self.structural_edge
        arrival=np.full(self.alive.shape,np.inf,np.float32)
        heap=[]
        for _ in range(3 if self.method=='GA' else 2):
            x=int(self.rng.integers(0,self.nw));y=int(self.rng.integers(0,self.nh))
            arrival[y,x]=0.;heapq.heappush(heap,(0.,y,x))
        while heap:
            value,y,x=heapq.heappop(heap)
            if value>arrival[y,x]+1e-4:continue
            for yy,xx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
                if 0<=yy<self.nh and 0<=xx<self.nw:
                    cost=value+float(resistance[yy,xx])
                    if cost<arrival[yy,xx]:
                        arrival[yy,xx]=cost;heapq.heappush(heap,(cost,yy,xx))
        arrival/=max(float(arrival.max()),1e-6)
        delay=.50+.16*(1-emo['intensity'])
        self.release=F.interpolate(T(arrival[...,None]),size=(self.h,self.w),mode='bilinear',align_corners=False)[0,0]*delay
        # Defocused colour left by the generated field keeps transitions alive.
        self.memory_mist=F.interpolate(F.adaptive_avg_pool2d(self.frozen,(4,7)),size=(self.h,self.w),mode='bilinear',align_corners=False)
        local=np.zeros_like(arrival)
        for label in np.unique(self.patch_labels):
            mask=self.patch_labels==label;local[mask]=arrival[mask].mean()*delay
        self.patch_release=self.expand(local)
        self.record['collapse_model']='local erosion into rigid fragments and persistent generated colour mist'

    def _render_collapse(self,canvas):
        q=float(np.clip((self.elapsed-self.break_t)/(self.duration*.995-self.break_t),0,1))
        if q==0:return self._render_complete()
        age=((q-self.patch_release)/(1-self.patch_release)).clamp(0,1)
        local_age=((q-self.release)/(1-self.release)).clamp(0,1)
        cam_x,cam_y=self._camera_flow()
        mood=self.profile['mood_style']
        wind=dict(vivid_mystery=(.035,-.025),dark_horror=(.065,.012),
                  bright_happy=(.025,-.055),dark_calm=(-.018,.035))[mood]
        strength=.7+.4*self._emotion_controls()['intensity']
        dx=cam_x-age.pow(1.3)*(wind[0]+self.patch_x*.080)*strength*1.65
        dy=cam_y-age.pow(1.3)*(wind[1]+self.patch_y*.050)*strength*1.65
        dissolve=((local_age-.08)/.90).clamp(0,1)
        alpha=1-dissolve.square()*(3-2*dissolve)
        # Fine GA matter, clustered CA matter; neither bends a wall like rubber.
        matter=self.dust if self.method=='GA' else self.expand(self.genes[...,0]*.65+self.phase/(2*math.pi)*.35)
        pores=((matter-dissolve*.8)*8).clamp(0,1)
        alpha=alpha*(1-dissolve*(1-pores))*(1-q**8)
        rgba=torch.cat([self.frozen*alpha[None,None],alpha[None,None]],1)
        grid=self.base_grid+torch.stack([dx*2,dy*2],-1)[None]
        moving=F.grid_sample(rgba,grid,mode='bilinear',padding_mode='zeros',align_corners=False)
        mist_grid=self.base_grid+torch.stack([cam_x*2+q*.018,cam_y*2-q*.010],-1)[None]
        mist=F.grid_sample(self.memory_mist,mist_grid,mode='bilinear',padding_mode='border',align_corners=False)
        # Residual generated material spans the handoff; there is no fade to black.
        base=canvas*.30+self._living_light(mist)*.70
        return (base*(1-moving[:,3:])+self._living_light(moving[:,:3])).clamp(0,1)


class PointGenesisGA(DreamConstructiveField):
    method='GA'


class StructuralDreamCA(DreamConstructiveField):
    method='CA'


MemoryCA=StructuralDreamCA
FieldEvolution=PointGenesisGA


class Particles:
    """스토리 문맥(떠오르는 기포, 낙하 파편, 햇살 먼지/깃털 등)에 맞춰 선택적으로만 동작하는 경량 입자계."""
    COLS = 14

    def __init__(self, max_count: int = 900):
        self.max_count = max_count
        self.P = np.zeros((0, self.COLS), np.float32)

    def spawn(self, x, y, vx, vy, life, grav=0.0, delay=0.0, size=None, color=None, amp=None, drag=0.0):
        n = len(x)
        if n == 0:
            return
        a = np.zeros((n, self.COLS), np.float32)
        a[:, 0], a[:, 1], a[:, 2], a[:, 3] = x, y, vx, vy
        a[:, 5] = life
        a[:, 6] = grav
        a[:, 7] = delay
        a[:, 8] = 0 if size is None else size
        a[:, 9:12] = 1.0 if color is None else color
        a[:, 12] = 0.45 if amp is None else amp
        a[:, 13] = drag
        self.P = np.vstack([self.P, a])[-self.max_count:]

    def step(self, wind: tuple[float, float]):
        P = self.P
        if not len(P):
            return
        P[:, 4] += DT
        act = (P[:, 4] > P[:, 7]).astype(np.float32)
        P[:, 3] += P[:, 6] * DT * act
        damp = np.clip(1.0 - P[:, 13] * DT, 0.85, 1.0)
        P[:, 2] *= damp
        P[:, 3] *= damp
        P[:, 0] += (P[:, 2] + wind[0]) * DT
        P[:, 1] += (P[:, 3] + wind[1]) * DT
        keep = (P[:, 4] < P[:, 5]) & (P[:, 0] > -16) & (P[:, 0] < W + 16) & (P[:, 1] > -16) & (P[:, 1] < H + 16)
        self.P = P[keep]

    def render(self, gate: float = 1.0) -> torch.Tensor:
        """절반 해상도(960x540)에서 고속 블러 후 업샘플링하여 프레임당 0.2ms 이내로 깔끔한 입자 표현."""
        hw, hh = W // 2, H // 2
        P = self.P
        if not len(P) or gate <= 1e-3:
            return torch.zeros((1, 3, H, W), device=DEV)
        a = P[:, 12] * np.sin(np.pi * np.clip(P[:, 4] / np.maximum(P[:, 5], 1e-3), 0.0, 1.0)) ** 0.75 * gate
        x = np.clip((P[:, 0] * 0.5).astype(np.int64), 0, hw - 1)
        y = np.clip((P[:, 1] * 0.5).astype(np.int64), 0, hh - 1)
        idx = torch.from_numpy(y * hw + x).to(DEV)
        w = torch.from_numpy((P[:, 9:12] * a[:, None]).astype(np.float32)).to(DEV)
        buf = torch.zeros((3, hh * hw), device=DEV)
        buf.index_add_(1, idx, w.T.contiguous())
        out_half = gblur(buf.view(1, 3, hh, hw), 1.15) * 4.2
        return F.interpolate(out_half, size=(H, W), mode="bilinear", align_corners=False)


def to_u8(img: torch.Tensor) -> np.ndarray:
    return (img[0].permute(1, 2, 0) * 255.0 + 0.5).clamp(0, 255).byte().cpu().numpy()


def contact_sheet(frames: list[tuple[float, np.ndarray]], path: Path, title: str = ""):
    if not frames:
        return
    tiles = []
    for t, im in frames:
        im_r = cv2.resize(im, (640, 360), interpolation=cv2.INTER_AREA)
        im_bgr = np.ascontiguousarray(im_r[..., ::-1])
        label = f"{title} {int(t // 60)}:{t % 60:04.1f}s".strip()
        cv2.putText(im_bgr, label, (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (15, 15, 15), 4, cv2.LINE_AA)
        cv2.putText(im_bgr, label, (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (248, 248, 248), 2, cv2.LINE_AA)
        tiles.append(im_bgr)
    cols = min(4, len(tiles))
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    sheet = np.vstack(rows)
    ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if ok:
        buf.tofile(str(path))
