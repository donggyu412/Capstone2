# -*- coding: utf-8 -*-
"""
core_engine.py — 꿈 재현 배경 시스템의 핵심 수학·물리·셀룰러 오토마타·사운드 동기화 모듈

구성 요소:
  1. 전역 시공간 규격 (1920x1080, 30fps, 300.0초, 9,000프레임, 기승전결 75초×4막, 3:15 클라이맥스)
  2. 감정 조건 매핑 (7종 감정 × 강도 → 셀룰러 성장률·망각률·호흡·변이·흐름 파라미터)
  3. 다대역 사운드 분석기 (저음/중음/고음 스펙트럼, 스펙트럼 플럭스 Onset, 물리 충격 이벤트 추출)
  4. 기억 셀룰러 오토마타 (MemoryCA: 발아 M · 자원 E · 지속 A · 망각 ex · 재기억 변위 Dm)
  5. 다중 스케일 점묘 격자 (Lattice: 8px 주 도트, 4px 미세 입자, 24px 보케 빛망울) 및 부유 입자계 (Particles)
"""
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
    """시스템 PATH, imageio_ffmpeg, 또는 로컬 벤더 경로에서 실행 가능한 ffmpeg 바이너리를 탐색."""
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
# 시공간 표준 규격 (Close-Ended 4막 구조)
# --------------------------------------------------------------------------------------
W, H, FPS, DUR = 1920, 1080, 30, 300.0
N = int(FPS * DUR)                       # 총 9,000 프레임
DT = 1.0 / FPS
CELL = 8
GW, GH = W // CELL, H // CELL            # 240 x 135 : 셀룰러 오토마타 격자 = 주 점묘 격자
SCENE_T = [0.0, 75.0, 150.0, 225.0, 300.0]
CLIMAX = 195.0                           # 3막 3분 15초 (전 장면 45초 지점) 클라이맥스 반전
PRE, POST = 7.0, 11.0                    # 장면 전환 오버랩: 다음 기억은 7초 먼저 발아하고 이전 기억은 11초 더 잔류
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

# 감정 → 셀룰러 오토마타 및 공간 흐름의 동역학 조건 파라미터
EMO = {
    "neutral":  dict(grow=1.00, decay=0.80, trail=0.80, jitter=0.05, breath=0.16, flow=0.60, vign=0.32,
                     warm=0.00, sat=1.05, flash=0.10, twist=0.00, flicker=0.00, mut=0.6),
    "happy":    dict(grow=1.40, decay=0.65, trail=0.80, jitter=0.15, breath=0.34, flow=1.00, vign=0.22,
                     warm=0.10, sat=1.20, flash=0.30, twist=0.00, flicker=0.00, mut=0.8),
    "sad":      dict(grow=0.60, decay=0.55, trail=0.92, jitter=0.05, breath=0.12, flow=0.45, vign=0.45,
                     warm=-0.08, sat=0.70, flash=0.00, twist=0.00, flicker=0.05, mut=0.5),
    "angry":    dict(grow=1.60, decay=1.60, trail=0.70, jitter=1.00, breath=0.50, flow=2.00, vign=0.40,
                     warm=0.14, sat=1.25, flash=0.50, twist=0.30, flicker=0.15, mut=1.6),
    "fear":     dict(grow=0.80, decay=1.25, trail=0.88, jitter=0.55, breath=0.26, flow=0.80, vign=0.70,
                     warm=-0.10, sat=0.88, flash=0.15, twist=0.25, flicker=0.30, mut=1.2),
    "surprise": dict(grow=1.50, decay=1.00, trail=0.78, jitter=0.30, breath=0.55, flow=1.20, vign=0.28,
                     warm=0.04, sat=1.15, flash=1.00, twist=0.05, flicker=0.10, mut=1.0),
    "disgust":  dict(grow=0.90, decay=1.20, trail=0.82, jitter=0.35, breath=0.24, flow=0.90, vign=0.50,
                     warm=0.00, sat=0.80, flash=0.10, twist=1.00, flicker=0.10, mut=1.4),
}


def emo_params(label_en: str, intensity: float) -> dict:
    """중립(neutral)을 기준점으로 감정 강도(intensity)에 비례해 동역학 파라미터를 보간."""
    k = float(np.clip(intensity / 0.6, 0.0, 1.3))
    base, e = EMO["neutral"], EMO[label_en]
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
    return cv2.GaussianBlur(a, (0, 0), s)


def vnoise(seed: int, scale: int, w: int = W, h: int = H) -> np.ndarray:
    rng = np.random.default_rng(seed)
    gh, gw = h // scale + 4, w // scale + 4
    small = rng.random((gh, gw)).astype(np.float32)
    big = cv2.resize(small, (gw * scale, gh * scale), interpolation=cv2.INTER_CUBIC)
    return np.clip(big[scale:scale + h, scale:scale + w], 0, 1)


def fbm(seed: int, scales=(240, 120, 60, 30), w: int = W, h: int = H) -> np.ndarray:
    acc, amp, tot = 0.0, 1.0, 0.0
    for i, s in enumerate(scales):
        acc = acc + vnoise(seed + i * 17, s, w, h) * amp
        tot += amp
        amp *= 0.55
    return (acc / tot).astype(np.float32)


def imread_u(path: Path) -> np.ndarray:
    """유니코드(한글) 경로를 안전하게 지원하며 1920x1080 float32 RGB(0..1)로 로드."""
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    return img[..., ::-1].astype(np.float32) / 255.0


def T(a) -> torch.Tensor:
    a = np.asarray(a, np.float32)
    a = a[None] if a.ndim == 2 else a.transpose(2, 0, 1)
    return torch.from_numpy(np.ascontiguousarray(a))[None].to(DEV)


def col(h: str) -> torch.Tensor:
    return torch.tensor(hexc(h), device=DEV).view(1, 3, 1, 1)


def lum(x: torch.Tensor) -> torch.Tensor:
    return 0.299 * x[:, 0:1] + 0.587 * x[:, 1:2] + 0.114 * x[:, 2:3]


_GK = {}


def gblur(x: torch.Tensor, sigma: float) -> torch.Tensor:
    if sigma <= 0:
        return x
    key = round(float(sigma), 3)
    if key not in _GK:
        k = int(sigma * 3) * 2 + 1
        ax = torch.arange(k, device=DEV, dtype=torch.float32) - k // 2
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


def up(x: torch.Tensor) -> torch.Tensor:
    return F.interpolate(x, size=(H, W), mode="bilinear", align_corners=False)


def ss(e0: float, e1: float, x: float) -> float:
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def tss(e0: float, e1: float, x: torch.Tensor) -> torch.Tensor:
    t = ((x - e0) / (e1 - e0)).clamp(0, 1)
    return t * t * (3 - 2 * t)


def gauss(t: float, c: float, w: float) -> float:
    return math.exp(-((t - c) / w) ** 2)


PXT = torch.arange(W, device=DEV, dtype=torch.float32).view(1, W).expand(H, W) + 0.5
PYT = torch.arange(H, device=DEV, dtype=torch.float32).view(H, 1).expand(H, W) + 0.5
UT, VT = (PXT / W)[None, None], (PYT / H)[None, None]


def make_grid(ox: float, oy: float, zoom: float, rot: float, disp=None, cx: float = W / 2, cy: float = H / 2) -> torch.Tensor:
    X, Y = PXT - cx, PYT - cy
    c, s = math.cos(rot), math.sin(rot)
    Xs = (c * X + s * Y) / zoom + cx - ox
    Ys = (-s * X + c * Y) / zoom + cy - oy
    if disp is not None:
        Xs = Xs + disp[0, 0]
        Ys = Ys + disp[0, 1]
    return torch.stack([Xs / W * 2 - 1, Ys / H * 2 - 1], -1)[None]


def sample_noise(tex: torch.Tensor, ox: float, oy: float, scale: float = 1.0, h: int = GH, w: int = GW) -> torch.Tensor:
    gy, gx = torch.meshgrid(torch.linspace(-1, 1, h, device=DEV), torch.linspace(-1, 1, w, device=DEV), indexing="ij")
    g = torch.stack([gx * 0.5 * scale + ox, gy * 0.5 * scale + oy], -1)[None]
    g = torch.remainder(g + 1, 2) - 1
    return F.grid_sample(tex, g, mode="bilinear", padding_mode="reflection", align_corners=False)


# --------------------------------------------------------------------------------------
# 다대역 사운드 분석기 (시나리오 고유 사운드 → 프레임별 물리/셀룰러 제어 신호)
# --------------------------------------------------------------------------------------
def ema(a: np.ndarray, tau: float) -> np.ndarray:
    k = 1 - math.exp(-DT / tau)
    y = np.zeros_like(a)
    acc = float(a[0])
    for i in range(len(a)):
        acc += (float(a[i]) - acc) * k
        y[i] = acc
    return y


def analyze_sound(path: Path) -> dict:
    """오디오/비디오 파일에서 48kHz 파형을 추출하여 저음/중음/고음 에너지 및 스펙트럼 플럭스 Onset을 계산."""
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    x = np.frombuffer(raw, np.float32)
    sr, hop, win = 48000, 48000 // FPS, 4096
    need = N * hop + win
    x = np.pad(x, (win // 2, max(0, need - len(x) - win // 2)))
    hann = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(win, 1 / sr)
    bands = {"low": (20, 180), "mid": (180, 1200), "high": (1200, 8000)}
    out = {k: np.zeros(N, np.float32) for k in bands}
    flux = np.zeros(N, np.float32)
    rms = np.zeros(N, np.float32)
    fmask = (freqs >= 150) & (freqs < 10000)
    prev = None
    for c0 in range(0, N, 600):
        idx = (np.arange(c0, min(N, c0 + 600)) * hop)[:, None] + np.arange(win)[None]
        seg = x[idx] * hann
        sp = np.abs(np.fft.rfft(seg, axis=1)).astype(np.float32)
        for k, (a, b) in bands.items():
            out[k][c0:c0 + len(sp)] = sp[:, (freqs >= a) & (freqs < b)].mean(1)
        ls = np.log1p(sp * 20)
        full = np.vstack([ls[:1] if prev is None else prev[None], ls])
        flux[c0:c0 + len(sp)] = np.maximum(np.diff(full, axis=0), 0)[:, fmask].mean(1)
        prev = ls[-1]
        rms[c0:c0 + len(sp)] = np.sqrt((seg ** 2).mean(1))

    def norm(a):
        return np.clip(a / (np.percentile(a, 96) + 1e-9), 0, 1.6).astype(np.float32)

    S = {k: ema(norm(v), 0.25) for k, v in out.items()}
    S["rms"] = ema(norm(rms), 0.3)
    fl = norm(flux)
    nov = np.clip(fl - ema(fl, 1.5) * 1.15, 0, None)
    thr = np.percentile(nov, 93) + 1e-6
    onsets, last = [], -999
    for i in range(1, N - 1):
        if nov[i] > thr and nov[i] >= nov[i - 1] and nov[i] >= nov[i + 1] and i - last >= 8:
            onsets.append(i)
            last = i
    on = np.zeros(N, np.float32)
    for f in onsets:
        on[f] = min(nov[f] / (thr * 2.5), 1.0)
    env = np.zeros(N, np.float32)
    acc = 0.0
    dec = math.exp(-DT / 0.35)
    for i in range(N):
        acc = max(float(on[i]), acc * dec)
        env[i] = acc
    pre = np.array([env[i:i + 48].max() for i in range(N)], np.float32)
    S["onset"] = env
    S["onset_raw"] = on
    S["pre"] = ema(pre, 0.4)
    low = norm(out["low"])
    S["low_nov"] = np.clip(ema(low, 0.15) - ema(low, 2.5), 0, None)
    S["onset_frames"] = onsets
    return S


def pick_peaks(sig, t0, t1, min_gap_s, thr_pct, rng, jitter=(1.0, 1.0)):
    f0, f1 = int(t0 * FPS), int(t1 * FPS)
    seg = sig[f0:f1]
    thr = np.percentile(seg, thr_pct)
    peaks, last = [], -10 ** 9
    gap = min_gap_s * FPS * rng.uniform(*jitter)
    for i in range(1, len(seg) - 1):
        if seg[i] > thr and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1] and (i - last) >= gap:
            peaks.append(f0 + i)
            last = i
            gap = min_gap_s * FPS * rng.uniform(*jitter)
    return peaks


def build_events(S: dict, seed: int) -> dict:
    """사운드 피크로부터 각 막(기·승·전·결)의 물리 사건 트리거 타임라인을 구성."""
    rng = np.random.default_rng(seed)
    ev = {}
    bounces = pick_peaks(S["low_nov"] + 0.5 * S["onset"], 5.0, 70.0, 2.6, 78, rng, (0.6, 2.2))
    big = int(51.0 * FPS)
    bounces = [b for b in bounces if abs(b - big) > 4 * FPS] + [big]
    bounces.sort()
    ev["s1_bounce"] = bounces

    creaks = pick_peaks(S["onset"] + 0.4 * S["mid"], 80.0, 138.0, 3.2, 80, rng, (0.8, 1.8))
    ev["s2_creak"] = creaks

    pushes = pick_peaks(S["low_nov"] + 0.3 * S["low"], 236.0, 284.0, 4.0, 75, rng, (0.8, 1.6))
    ev["s4_pushes"] = pushes
    return ev


# --------------------------------------------------------------------------------------
# Open-Ended 핵심: 기억 셀룰러 오토마타 (MemoryCA)
# --------------------------------------------------------------------------------------
class MemoryCA:
    """
    240 x 135 격자 기반 기억 셀룰러 오토마타.
    각 셀은 공간의 한 조각에 대한 기억 상태를 나타낸다:
      - M  : 현재 기억이 떠오른 활성도 (0..1)
      - E  : 세포 기억 유지 에너지 자원 (0..1)
      - A  : 기억이 연속으로 유지된 체류 시간
      - ex : 에너지 고갈로 인한 망각/박리 상태 (0 또는 1)
      - Dm : 망각 후 재기억될 때 발생하는 공간 어긋남 변위 벡터 (2채널)
    """

    def __init__(self, hab: torch.Tensor, seed: int):
        self.hab = hab
        self.g = torch.Generator(device=DEV).manual_seed(seed)
        z = torch.zeros((1, 1, GH, GW), device=DEV)
        self.M, self.A, self.ex = z.clone(), z.clone(), z.clone()
        self.E = 0.75 + 0.25 * self.rand()
        self.cons = 0.7 + 0.6 * self.rand()
        self.Dm = torch.zeros((1, 2, GH, GW), device=DEV)
        k = torch.ones((1, 1, 3, 3), device=DEV)
        k[0, 0, 1, 1] = 0
        self.K = k / 8.0
        self.births = 0.0
        self.forgets = 0.0

    def rand(self, c: int = 1) -> torch.Tensor:
        return torch.rand((1, c, GH, GW), generator=self.g, device=DEV)

    def step(self, p: dict, onset: float, gate: float, hab_dyn=None, force_decay: float = 0.0, seed_bias=None):
        hab = self.hab if hab_dyn is None else (self.hab + hab_dyn).clamp(0, 1)
        M = self.M
        nb = F.conv2d(F.pad(M, (1, 1, 1, 1), mode="replicate"), self.K)
        spark_p = (0.0011 * p["grow"] + 0.006 * onset * p["flash"]) * hab * gate
        spark = (self.rand() < spark_p).float()
        if seed_bias is not None:
            spark = torch.maximum(spark, (self.rand() < seed_bias * 0.03 * gate).float())
        birth = DT * p["grow"] * hab ** 1.2 * (nb * 2.6) * self.E * (1 - 0.9 * self.ex) * (self.rand() * 2.0) * gate
        M = M + (birth + spark * 0.55) * (1 - M)
        decay = DT * (p["decay"] * (0.11 * (1 - hab) + 0.012) + self.ex * 0.6 + force_decay)
        M = (M * (1 - decay)).clamp(0, 1)
        self.E = (self.E + DT * (0.032 * (1 - self.E) - 0.021 * self.cons * M * (1 + self.A / 22.0))).clamp(0, 1)
        prev_ex = self.ex
        self.ex = torch.where(
            self.E < 0.17,
            torch.ones_like(self.ex),
            torch.where(self.E > 0.55, torch.zeros_like(self.ex), self.ex),
        )
        self.A = torch.where(M > 0.35, self.A + DT, self.A * 0.97)
        recovered = prev_ex * (1 - self.ex)
        if float(recovered.sum()) > 0:
            self.Dm = self.Dm + recovered * torch.randn((1, 2, GH, GW), generator=self.g, device=DEV) * 9.0 * p["mut"]
        self.Dm = gblur(self.Dm * 0.9965, 0.8)
        self.births += float(spark.sum())
        self.forgets += float((self.ex - prev_ex).clamp(min=0).sum())
        self.M = M


# --------------------------------------------------------------------------------------
# 다중 스케일 점묘 격자 (Lattice) 및 부유 입자계 (Particles)
# --------------------------------------------------------------------------------------
class Lattice:
    """셀룰러 활성도와 사운드 호흡에 따라 개별 도트 반경이 실시간으로 맥동하는 점묘 렌더러."""

    def __init__(self, cell: int, seed: int, density: float = 1.0, aa: float = 1.0, rmax: float = 0.46, jit: float = 0.16):
        self.cell, self.aa, self.rmax, self.jit = cell, aa, rmax, jit
        gh, gw = H // cell, W // cell
        self.gh, self.gw = gh, gw
        g = torch.Generator(device=DEV).manual_seed(seed)
        R = lambda: torch.rand((1, 1, gh, gw), generator=g, device=DEV)
        self.phase = R() * 6.2832
        self.jx0, self.jy0 = (R() * 2 - 1) * jit * cell, (R() * 2 - 1) * jit * cell
        self.keep = (R() < density).float()
        self.sizevar = 0.65 + 0.7 * R()
        self.order = R()
        self.freq = 0.4 + 1.2 * R()
        self.lx = ((torch.arange(W, device=DEV) % cell).float() + 0.5).view(1, 1, 1, W)
        self.ly = ((torch.arange(H, device=DEV) % cell).float() + 0.5).view(1, 1, H, 1)

    def upn(self, a: torch.Tensor) -> torch.Tensor:
        return F.interpolate(a, scale_factor=self.cell, mode="nearest")

    def render(self, Cc: torch.Tensor, Vc: torch.Tensor, t: float, breath: float, gate: float, swell: float = 0.0) -> torch.Tensor:
        wob = torch.sin(t * self.freq + self.phase)
        alive = (self.order < gate).float() * self.keep
        r = self.cell * self.rmax * torch.sqrt(Vc.clamp(0, 1)) * self.sizevar * (1 + breath * wob + swell) * alive
        r = r.clamp(0, self.cell * (0.5 - self.jit) + 0.6)
        jx = self.jx0 + torch.cos(t * 0.37 + self.phase) * 0.06 * self.cell
        jy = self.jy0 + torch.sin(t * 0.29 + self.phase) * 0.06 * self.cell
        d = torch.hypot(self.lx - self.upn(self.cell / 2 + jx), self.ly - self.upn(self.cell / 2 + jy))
        m = ((self.upn(r) - d) / self.aa + 0.5).clamp(0, 1)
        return self.upn(Cc) * m


class Particles:
    """물보라, 빗방울, 물방울, 황금빛 먼지 등 공간의 물리적 부유 입자를 시뮬레이션."""
    COLS = 14

    def __init__(self):
        self.P = np.zeros((0, self.COLS), np.float32)

    def spawn(self, x, y, vx, vy, life, grav=0.0, delay=0.0, size=None, color=None, amp=None, drag=0.0):
        n = len(x)
        a = np.zeros((n, self.COLS), np.float32)
        a[:, 0], a[:, 1], a[:, 2], a[:, 3] = x, y, vx, vy
        a[:, 5] = life
        a[:, 6] = grav
        a[:, 7] = delay
        a[:, 8] = 0 if size is None else size
        a[:, 9:12] = 1.0 if color is None else color
        a[:, 12] = 0.5 if amp is None else amp
        a[:, 13] = drag
        self.P = np.vstack([self.P, a])[-5000:]

    def step(self, wind):
        P = self.P
        if not len(P):
            return
        P[:, 4] += DT
        act = (P[:, 4] > P[:, 7]).astype(np.float32)
        P[:, 3] += P[:, 6] * DT * act
        damp = 1 - P[:, 13] * DT
        P[:, 2] *= damp
        P[:, 3] *= damp
        P[:, 0] += (P[:, 2] + wind[0]) * DT
        P[:, 1] += (P[:, 3] + wind[1]) * DT
        keep = (P[:, 4] < P[:, 5]) & (P[:, 0] > -20) & (P[:, 0] < W + 20) & (P[:, 1] > -20) & (P[:, 1] < H + 20)
        self.P = P[keep]

    def render(self, gate: float) -> torch.Tensor:
        out = torch.zeros((1, 3, H, W), device=DEV)
        P = self.P
        if not len(P):
            return out
        a = P[:, 12] * np.sin(np.pi * np.clip(P[:, 4] / P[:, 5], 0, 1)) ** 0.8 * gate
        for big, sigma in ((0, 1.1), (1, 3.2)):
            sel = P[:, 8] == big
            if not sel.any():
                continue
            q = P[sel]
            x = np.clip(q[:, 0].astype(np.int64), 0, W - 1)
            y = np.clip(q[:, 1].astype(np.int64), 0, H - 1)
            idx = torch.from_numpy(y * W + x).to(DEV)
            w = torch.from_numpy((q[:, 9:12] * a[sel, None]).astype(np.float32)).to(DEV)
            buf = torch.zeros((3, H * W), device=DEV)
            buf.index_add_(1, idx, w.T.contiguous())
            buf = gblur(buf.view(1, 3, H, W), sigma) * (2 * math.pi * sigma * sigma * 0.85)
            out = out + buf
        return out


def to_u8(img: torch.Tensor) -> np.ndarray:
    return (img[0].permute(1, 2, 0) * 255 + 0.5).clamp(0, 255).byte().cpu().numpy()


def contact_sheet(frames: list[tuple[float, np.ndarray]], path: Path, title: str = ""):
    tiles = []
    for t, im in frames:
        im = cv2.resize(im, (640, 360), interpolation=cv2.INTER_AREA)
        im = np.ascontiguousarray(im[..., ::-1])
        cv2.putText(im, f"{int(t // 60)}:{int(t % 60):02d}", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2, cv2.LINE_AA)
        tiles.append(im)
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    sheet = np.vstack(rows)
    ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if ok:
        buf.tofile(str(path))
