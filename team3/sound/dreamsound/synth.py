"""소리 합성 부품 — numpy/scipy 만 쓴다 (CPU · GPU 없이도 돈다).

  · 모달 합성  : 오브제 실루엣 → 공명 모드(주파수·감쇠·세기) → 두드림/문지름 소리
                 (van den Doel et al. 2001 의 모달 모델 · Clarke et al. 2021 DiffImpact 의 '물리 파라미터 → 소리' 관점 차용)
  · 사건 합성  : 사건 분류표(물방울·전기 험·종이…)마다 절차적 합성기
  · 공간       : 지수 감쇠 잡음 임펄스 응답 리버브 (좌우 따로 → 넓이)
난수는 전부 '내용에서 나온 시드'의 np.random.default_rng 로만 — 같은 입력이면 같은 소리(재현 가능).
"""
import math

import numpy as np
from scipy import signal

SR = 44100


def rng_for(*keys):
    """내용 → 시드. 장면·오브제 이름이 같으면 같은 난수열."""
    h = 2166136261
    for k in keys:
        for ch in str(k).encode('utf-8'):
            h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return np.random.default_rng(h)


def norm(y, peak=0.9):
    m = float(np.max(np.abs(y))) if len(y) else 0.0
    return (y * (peak / m)).astype(np.float32) if m > 1e-9 else y.astype(np.float32)


def env(n, sr, attack=0.005, decay=0.5, curve='exp'):
    t = np.arange(n) / sr
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    d = np.exp(-6.9 * np.maximum(t - attack, 0) / max(decay, 1e-3)) if curve == 'exp' else np.clip(1 - t / decay, 0, 1)
    return a * d


def bandpass(y, lo, hi, sr, order=2):
    lo = max(20.0, min(lo, sr / 2 - 200))
    hi = max(lo + 10, min(hi, sr / 2 - 100))
    sos = signal.butter(order, [lo, hi], btype='band', fs=sr, output='sos')
    return signal.sosfilt(sos, y)


def lowpass(y, hz, sr, order=2):
    hz = max(40.0, min(hz, sr / 2 - 100))
    return signal.sosfilt(signal.butter(order, hz, btype='low', fs=sr, output='sos'), y)


def highpass(y, hz, sr, order=2):
    hz = max(20.0, min(hz, sr / 2 - 200))
    return signal.sosfilt(signal.butter(order, hz, btype='high', fs=sr, output='sos'), y)


def brown(n, rng):
    x = signal.lfilter([1], [1, -0.995], rng.standard_normal(n))   # 새는 적분기 = 갈색 잡음
    x = highpass(x, 20, SR, 1)
    return x / (np.max(np.abs(x)) + 1e-9)


def resonator_bank(exc, freqs, decays, amps, sr):
    """여기 신호를 2차 공명기 여럿에 통과 — 모달 합성의 핵심."""
    out = np.zeros_like(exc, dtype=np.float64)
    for f, d, a in zip(freqs, decays, amps):
        if f >= sr / 2 - 100 or a <= 0:
            continue
        r = math.exp(-6.9 / (max(d, 0.01) * sr))
        w = 2 * math.pi * f / sr
        b, aa = [1 - r], [1, -2 * r * math.cos(w), r * r]
        out += a * signal.lfilter(b, aa, exc)
    return out


def reverb_ir(t60, sr, seed=0, predelay=0.01, damp=0.5):
    n = int(sr * min(10.0, max(0.2, t60)))
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    ir = rng.standard_normal(n) * np.exp(-6.9 * t / t60)
    # 시간이 갈수록 고역이 먼저 죽는다 — 두 대역을 다른 속도로 감쇠
    lo = lowpass(ir, 2500, sr, 1)
    ir = lo + (ir - lo) * np.exp(-6.9 * t / max(0.15, t60 * (1 - 0.8 * damp)))
    ir = np.concatenate([np.zeros(int(predelay * sr)), ir])
    return (ir / (np.sqrt(np.sum(ir ** 2)) + 1e-9)).astype(np.float32)


def convolve(y, ir):
    return signal.fftconvolve(y, ir)[:len(y)]


def pitch(y, semitones):
    """재생 속도로 음높이를 옮긴다 (테이프처럼 길이도 함께 변함 — 배경 엔진 preservesPitch=false 와 같은 성격)."""
    if abs(semitones) < 1e-3:
        return y
    rate = 2 ** (semitones / 12)
    idx = np.arange(0, len(y) - 1, rate)
    return np.interp(idx, np.arange(len(y)), y).astype(np.float32)


# ── 오브제 실루엣 → 모달 파라미터 ─────────────────────────────────────────
def modal_params(f):
    """오브제 형태 특징 → (기본 주파수, 배음비, 감쇠, 세기).

    교차감각 대응(PAPERS.md §2)을 그대로 수식으로:
      면적 ↑ → 낮은 음            (크기–음높이 대응)
      밝기 ↑ → 높은 음            (명도–음높이 대응)
      각짐 ↑ → 비조화 배음·짧은 감쇠·밝은 음색 (모양–음색: 각진 형태 ↔ 날카로운 소리)
      대칭 ↑ → 조화 배음          (규칙적인 형태 ↔ 규칙적인 배음)
      채도 ↑ → 고차 배음이 살아남  (색의 선명도 ↔ 음색의 선명도)
      단단함(solidity) ↑ → 길게 울림
    10-08: 그림 인식(vision.py · SigLIP 2)이 재질을 알아냈으면 그 재질의 물리적 성격으로 한 번 더 민다
      (예: 종이는 거의 울리지 않고, 금속은 길고 비조화롭게, 유리는 높고 맑게) — 인식 확신이 낮으면 덜 민다."""
    area = f.get('area', 0.2)
    luma = f.get('luma', 0.5)
    ang = f.get('angularity', 0.3)
    sym = f.get('symmetry', 0.5)
    sat = f.get('saturation', 0.1)
    sol = f.get('solidity', 0.7)
    f0 = 70 * 2 ** (4.0 * (0.55 * (1 - math.sqrt(max(area, 0))) + 0.45 * luma))
    n = int(5 + 7 * (1 - sol) + 4 * sat)
    B = 0.0005 + 0.06 * ang * (1 - 0.6 * sym)           # 뻣뻣한 현의 비조화 계수처럼
    ratios = [k * math.sqrt(1 + B * k * k) for k in range(1, n + 1)]
    tilt = 2.2 - 1.4 * sat - 0.8 * ang
    amps = [k ** (-tilt) for k in range(1, n + 1)]
    t60 = 0.25 + 2.6 * sol * (1 - 0.6 * ang) * (0.5 + area)
    mat = MAT_MODAL.get(f.get('material'))
    if mat:
        w = material_weight(f)
        fm, tm, badd, tadd = mat
        f0 *= fm ** w
        t60 *= tm ** w
        B += badd * w
        ratios = [k * math.sqrt(1 + B * k * k) for k in range(1, n + 1)]
        tilt += tadd * w
        amps = [k ** (-tilt) for k in range(1, n + 1)]
    decays = [t60 / (1 + 0.35 * (k - 1) * (0.5 + ang)) for k in range(1, n + 1)]
    return f0, ratios, decays, amps


# 재질 → (기본음 배율, 울림 길이 배율, 비조화 더하기, 배음 기울기 더하기[+ = 어둡게])
# 근거: 재질별 감쇠·비조화의 크기 순서 (Klatzky et al. 2000 — 감쇠율이 재질 판단의 주된 단서 · Rossing 의 막대·판 모드비)
MAT_MODAL = {
    'metal':   (1.0, 2.2, 0.030, -0.4),
    'glass':   (1.6, 1.5, 0.006, -0.6),
    'wood':    (0.9, 0.35, 0.000, 0.6),
    'stone':   (0.8, 0.25, 0.010, 0.8),
    'paper':   (1.2, 0.12, 0.050, 0.2),
    'fabric':  (0.7, 0.08, 0.000, 1.2),
    'liquid':  (1.3, 0.30, 0.000, 0.3),
    'organic': (0.6, 0.15, 0.000, 1.0),
    'shadow':  (0.5, 2.5, 0.000, 1.4),
}
NOISY = ('paper', 'fabric', 'organic')        # 두드리면 '탁' 대신 '사각' — 잡음으로 들뜨게


def material_weight(f):
    """인식 확신(소프트맥스 확률) → 재질을 미는 정도 0~1. 9개 중 하나라 0.2 이하는 거의 모름."""
    return float(min(1.0, max(0.0, (f.get('material_p', 0.0) - 0.15) / 0.45)))


def modal_strike(f, sr=SR, variant=0, seed=0):
    """두드림 — 칠 자리(variant)마다 모드 세기가 달라진다(sin(kπx))."""
    f0, ratios, decays, amps = modal_params(f)
    x = 0.13 + 0.27 * variant
    amps = [a * abs(math.sin((k + 1) * math.pi * x)) + 0.05 * a for k, a in enumerate(amps)]
    dur = min(5.0, max(decays) * 1.3 + 0.1)
    n = int(sr * dur)
    rng = np.random.default_rng(seed + variant)
    exc = np.zeros(n)
    hard = 0.0004 + 0.004 * (1 - f.get('angularity', 0.3))     # 각질수록 짧고 단단한 타격
    m = max(2, int(hard * sr))
    exc[:m] = np.hanning(2 * m)[m:] * (1 + 0.1 * rng.standard_normal(m))
    mat, w = f.get('material'), material_weight(f)
    if mat in NOISY and w > 0:                               # 종이·천·살갗: 짧은 잡음 다발로 들뜬다 (사각·툭)
        L = int(sr * (0.03 + 0.05 * w))
        exc[:L] += w * 0.6 * rng.standard_normal(L) * np.linspace(1, 0, L) ** 2
    parts = max(1, int(f.get('parts', 1)))
    for p in range(1, min(parts, 6)):                       # 흩어진 조각 = 뒤따르는 작은 타격들
        at = int(sr * (0.04 + 0.09 * p + 0.02 * rng.random()))
        if at + m < n:
            exc[at:at + m] += 0.35 / p * np.hanning(2 * m)[m:]
    y = resonator_bank(exc, [f0 * r for r in ratios], decays, amps, sr)
    if mat == 'liquid' and w > 0:                            # 액체: 기포처럼 위로 휘는 음 (Minnaert 공명의 상승 처프)
        L = min(n, int(sr * 0.12))
        tt = np.arange(L) / sr
        fr = f0 * 2 * (1 + 2.5 * tt / tt[-1])
        y[:L] += w * 0.5 * np.sin(2 * np.pi * np.cumsum(fr) / sr) * np.exp(-tt * 30)
    if mat == 'shadow' and w > 0:                            # 그림자: 치는 소리가 아니라 부풀어 오르는 소리
        y = y * (1 - w + w * np.minimum(1, np.arange(n) / (sr * 0.4)))
    return norm(y * env(n, sr, 0.0005, dur, 'lin'))


def modal_drone(f, sr=SR, dur=6.0, seed=0):
    """문지름 — 잡음으로 모드를 계속 울린다. 세로로 긴 형태일수록 음이 천천히 처진다."""
    f0, ratios, decays, amps = modal_params(f)
    n = int(sr * dur)
    rng = np.random.default_rng(seed + 99)
    exc = lowpass(rng.standard_normal(n), 3000, sr) * 0.02
    sweep = 1 - 0.04 * min(3.0, f.get('aspect', 1.0)) * np.linspace(0, 1, n)
    y = np.zeros(n)
    for r, d, a in zip(ratios, decays, amps):
        fr = f0 * r * sweep
        if fr[0] >= sr / 2 - 200:
            continue
        ph = 2 * np.pi * np.cumsum(fr) / sr
        y += a * np.sin(ph + rng.random() * 6.28) * (0.6 + 0.4 * np.sin(2 * np.pi * (0.07 + 0.05 * rng.random()) * np.arange(n) / sr))
    y = y * 0.6 + resonator_bank(exc, [f0 * r for r in ratios[:6]], [d * 2 for d in decays[:6]], amps[:6], sr) * 4
    e = np.minimum(1, np.minimum(np.arange(n) / (sr * 1.5), (n - np.arange(n)) / (sr * 1.5)))
    return norm(y * e, 0.7)


# ── 사건 분류표의 절차적 합성기 ─────────────────────────
def ev_drip(sr, rng):
    n = int(sr * 0.35)
    t = np.arange(n) / sr
    f0 = 700 + 900 * rng.random()
    fr = f0 * (1 + 1.8 * (1 - np.exp(-t / 0.012)))          # 물방울 공명은 위로 휜다
    y = np.sin(2 * np.pi * np.cumsum(fr) / sr) * np.exp(-t / 0.045)
    y[:int(sr * 0.002)] += rng.standard_normal(int(sr * 0.002)) * 0.4
    return norm(y)


def ev_electric(sr, rng):
    n = int(sr * 3.0)
    t = np.arange(n) / sr
    hz = 60.0
    y = sum((1.0 / k) * np.sin(2 * np.pi * hz * k * t) for k in (1, 2, 3, 5, 7))
    buzz = bandpass(signal.sawtooth(2 * np.pi * hz * 2 * t), 1800, 4200, sr) * 0.3
    gate = np.repeat(rng.random(int(3.0 * 25)) > 0.25, int(sr / 25) + 1)[:n].astype(float)
    gate = lowpass(gate, 60, sr, 1)
    return norm((y * 0.5 + buzz) * (0.35 + 0.65 * gate), 0.6)


def ev_creak(sr, rng):
    n = int(sr * 1.8)
    exc = np.zeros(n)
    t = 0.0
    while t < 1.7:
        exc[int(t * sr)] = 1 - 0.5 * rng.random()
        t += 0.006 + 0.03 * (0.5 + 0.5 * math.sin(t * 3.0)) * (0.7 + 0.6 * rng.random())
    f = 280 + 300 * rng.random()
    y = resonator_bank(exc, [f, f * 2.3, f * 3.9], [0.08, 0.05, 0.03], [1, 0.5, 0.3], sr)
    return norm(y * env(n, sr, 0.2, 1.8, 'lin'))


def ev_rustle(sr, rng):
    n = int(sr * 1.4)
    y = highpass(rng.standard_normal(n), 1500, sr)
    e = np.zeros(n)
    for _ in range(int(8 + 10 * rng.random())):
        at = int(rng.random() * n * 0.85)
        ln = int(sr * (0.01 + 0.06 * rng.random()))
        e[at:at + ln] += np.hanning(ln)[:len(e[at:at + ln])] * (0.3 + rng.random())
    return norm(y * lowpass(e, 200, sr, 1))


def ev_crack(sr, rng):
    n = int(sr * 0.7)
    exc = np.zeros(n)
    for k in range(int(2 + 4 * rng.random())):
        exc[int(sr * 0.012 * k * rng.random())] = 1.0
    fs = [2000 + 5000 * rng.random() for _ in range(6)]
    y = resonator_bank(exc, fs, [0.02 + 0.05 * rng.random() for _ in fs], [1] * 6, sr)
    y += highpass(rng.standard_normal(n), 2500, sr) * np.exp(-np.arange(n) / (sr * 0.03)) * 0.5
    return norm(y)


def ev_liquid(sr, rng):
    n = int(sr * 2.0)
    y = np.zeros(n)
    for _ in range(int(5 + 8 * rng.random())):
        at = int(rng.random() * (n - sr * 0.2))
        r = 0.5 + 3 * rng.random()                           # 기포 반지름(mm) → 공명 3.26/r kHz (Minnaert)
        f = 3260 / r
        ln = int(sr * 0.12)
        tt = np.arange(ln) / sr
        y[at:at + ln] += np.sin(2 * np.pi * f * (1 + 0.6 * tt / 0.12) * tt) * np.exp(-tt / (0.02 + 0.03 * rng.random())) * (0.3 + rng.random())
    return norm(lowpass(y, 2500, sr) + lowpass(rng.standard_normal(n), 300, sr) * 0.05)


def ev_ice(sr, rng):
    n = int(sr * 3.0)
    t = np.arange(n) / sr
    y = np.zeros(n)
    for _ in range(7):
        f = 2500 + 6500 * rng.random()
        y += np.sin(2 * np.pi * f * t + 6.28 * rng.random()) * (0.5 + 0.5 * np.sin(2 * np.pi * (0.3 + rng.random()) * t))
    return norm(y * env(n, sr, 0.6, 3.0, 'lin'), 0.4)


def ev_breath(sr, rng):
    n = int(sr * 4.0)
    t = np.arange(n) / sr
    y = bandpass(rng.standard_normal(n), 250, 1400, sr)
    e = np.sin(np.pi * t / 4.0) ** 2 * (0.6 + 0.4 * np.sin(2 * np.pi * t / 2.0) ** 2)
    return norm(y * e, 0.6)


def ev_metal(sr, rng):
    f = {'area': 0.6, 'luma': 0.2, 'angularity': 0.7, 'symmetry': 0.3, 'saturation': 0.2, 'solidity': 0.9}
    return modal_strike(f, sr, variant=int(rng.integers(0, 3)), seed=int(rng.integers(0, 1 << 30)))


def ev_thump(sr, rng):
    n = int(sr * 0.8)
    t = np.arange(n) / sr
    fr = 38 + 30 * np.exp(-t / 0.05)
    y = np.sin(2 * np.pi * np.cumsum(fr) / sr) * np.exp(-t / 0.18)
    y += lowpass(rng.standard_normal(n), 250, sr) * np.exp(-t / 0.05) * 0.3
    return norm(y)


def ev_friction(sr, rng):
    n = int(sr * 2.0)
    x = rng.standard_normal(n)
    d = int(sr / (120 + 200 * rng.random()))
    y = signal.lfilter([1], np.r_[1, np.zeros(d - 1), -0.85], x)
    y = bandpass(y, 150, 3000, sr) * (0.5 + 0.5 * np.sin(2 * np.pi * (0.8 + rng.random()) * np.arange(n) / sr))
    return norm(y * env(n, sr, 0.3, 2.0, 'lin'), 0.6)


def ev_presence(sr, rng):
    n = int(sr * 6.0)
    t = np.arange(n) / sr
    f = 38 + 25 * rng.random()
    y = sum(np.sin(2 * np.pi * f * m * (1 + 0.003 * k) * t) / m for k, m in enumerate((1, 1.5, 2, 3)))
    return norm(lowpass(y, 400, sr) * env(n, sr, 2.0, 6.0, 'lin'), 0.6)


def ev_wind(sr, rng):
    n = int(sr * 5.0)
    t = np.arange(n) / sr
    gust = lowpass(rng.standard_normal(n), 0.6, sr, 1)
    gust = 0.35 + 0.65 * (gust - gust.min()) / (np.ptp(gust) + 1e-9)
    y = bandpass(rng.standard_normal(n), 300, 2500, sr) * gust
    f = 700 + 500 * rng.random()                              # 갈대 틈 휘파람
    y += np.sin(2 * np.pi * np.cumsum(f * (1 + 0.05 * gust)) / sr) * gust ** 3 * 0.15
    return norm(y * env(n, sr, 1.0, 5.0, 'lin'), 0.6)


def ev_rain(sr, rng):
    n = int(sr * 3.0)
    y = highpass(rng.standard_normal(n), 1500, sr) * 0.08
    for _ in range(int(60 + 60 * rng.random())):              # 작은 빗방울들
        at = int(rng.random() * (n - 800))
        f = 2000 + 4000 * rng.random()
        k = np.arange(600) / sr
        y[at:at + 600] += np.sin(2 * np.pi * f * k) * np.exp(-k / 0.004) * (0.2 + 0.6 * rng.random())
    return norm(y, 0.5)


def ev_snow(sr, rng):
    n = int(sr * 4.0)
    y = bandpass(rng.standard_normal(n), 3000, 9000, sr) * 0.04
    for _ in range(int(15 + 15 * rng.random())):
        at = int(rng.random() * (n - 200))
        y[at:at + 120] += rng.standard_normal(120) * np.hanning(120) * 0.15
    return norm(y * env(n, sr, 1.5, 4.0, 'lin'), 0.35)


def ev_knock(sr, rng):
    n = int(sr * 0.9)
    exc = np.zeros(n)
    for k in range(int(1 + 3 * rng.random())):
        exc[int(sr * (0.18 * k))] = 1.0 - 0.2 * k
    f = 180 + 250 * rng.random()
    y = resonator_bank(exc, [f, f * 2.7, f * 5.1], [0.09, 0.05, 0.03], [1, 0.5, 0.25], sr)
    return norm(y)


def ev_door(sr, rng):
    y = np.concatenate([ev_creak(sr, rng)[:int(sr * 1.2)] * 0.7, np.zeros(int(sr * 0.1))])
    th = ev_thump(sr, rng) * 0.9
    out = np.zeros(len(y) + len(th))
    out[:len(y)] += y
    out[len(y) - int(sr * 0.05):len(y) - int(sr * 0.05) + len(th)] += th
    return norm(out)


def ev_alarm(sr, rng):
    n = int(sr * 3.0)
    t = np.arange(n) / sr
    f = 400 + 300 * rng.random()
    gate = (np.sin(2 * np.pi * 1.2 * t) > 0).astype(float)
    y = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2.01 * t)) * lowpass(gate, 40, sr, 1)
    return norm(y, 0.5)


def ev_machine(sr, rng):
    n = int(sr * 4.0)
    t = np.arange(n) / sr
    f = 45 + 40 * rng.random()
    y = sum(np.sin(2 * np.pi * f * k * t) / k for k in (1, 2, 3, 4))
    y += bandpass(rng.standard_normal(n), 800, 3000, sr) * 0.1 * (0.5 + 0.5 * np.sin(2 * np.pi * (6 + 4 * rng.random()) * t))
    return norm(y * env(n, sr, 0.5, 4.0, 'lin'), 0.6)


def ev_clock(sr, rng):
    n = int(sr * 2.0)
    exc = np.zeros(n)
    for k in range(4):
        exc[int(sr * 0.5 * k)] = 1.0 if k % 2 == 0 else 0.6
    f = 2500 + 1500 * rng.random()
    return norm(resonator_bank(exc, [f, f * 1.7, f * 2.9], [0.02, 0.015, 0.01], [1, .6, .3], sr))


def ev_flow(sr, rng):
    n = int(sr * 4.0)
    y = bandpass(rng.standard_normal(n), 400, 3500, sr)
    m = lowpass(rng.standard_normal(n), 3, sr, 1)
    y *= 0.6 + 0.4 * m / (np.max(np.abs(m)) + 1e-9)
    return norm(y, 0.5)


def ev_fire(sr, rng):
    n = int(sr * 3.0)
    y = lowpass(rng.standard_normal(n), 900, sr) * 0.15
    for _ in range(int(20 + 30 * rng.random())):
        at = int(rng.random() * (n - 400))
        y[at:at + 300] += highpass(rng.standard_normal(300), 2000, sr) * np.exp(-np.arange(300) / 40) * (0.3 + rng.random())
    return norm(y, 0.6)


def ev_glass(sr, rng):
    f = {'area': 0.15, 'luma': 0.9, 'angularity': 0.2, 'symmetry': 0.9, 'saturation': 0.4, 'solidity': 0.95}
    return modal_strike(f, sr, variant=int(rng.integers(0, 3)), seed=int(rng.integers(0, 1 << 30)))


def ev_animal(sr, rng):
    n = int(sr * 1.2)
    t = np.arange(n) / sr
    f0 = 250 + 500 * rng.random()
    contour = f0 * (1 + 0.4 * np.sin(np.pi * t / 1.2)) * (1 - 0.3 * t)
    src = signal.sawtooth(2 * np.pi * np.cumsum(contour) / sr)
    y = sum(bandpass(src, fm * 0.85, fm * 1.15, sr) * a for fm, a in ((700, 1), (1200, .6), (2600, .3)))
    burst = np.zeros(n)
    for k in range(int(1 + 2 * rng.random())):
        a = int(sr * 0.35 * k)
        burst[a:a + int(sr * 0.22)] = np.hanning(int(sr * 0.22))
    return norm(y * burst, 0.6)


# ── 낱말 소리용 합성기 (10-08) — 사건 분류표 24종에 없던 '손 · 글씨 · 먼지 · 압정 · 가슴 · 천' 같은 낱말의 소리 ──
def ev_touch(sr, rng):
    """손이 닿고 스치는 소리 — 살갗 마찰: 낮게 걸러진 잡음의 짧은 쓸림 두세 번."""
    n = int(sr * 1.2)
    y = np.zeros(n)
    t = 0.02
    for _ in range(int(2 + 2 * rng.random())):
        L = int(sr * rng.uniform(0.12, 0.3))
        i = int(t * sr)
        if i + L >= n:
            break
        y[i:i + L] += bandpass(rng.standard_normal(L), 300, 2200, sr) * np.hanning(L) * rng.uniform(0.5, 1)
        t += L / sr + rng.uniform(0.05, 0.2)
    return norm(y, 0.6)


def ev_pen(sr, rng):
    """글씨 · 잉크 — 펜촉이 종이를 긁는 짧은 획들 (좁은 대역 잡음 + 빠른 떨림)."""
    n = int(sr * 1.6)
    t = np.arange(n) / sr
    y = np.zeros(n)
    at = 0.05
    while at < 1.45:
        L = int(sr * rng.uniform(0.06, 0.22))
        i = int(at * sr)
        seg = bandpass(rng.standard_normal(L), 2500, 6500, sr) * np.hanning(L)
        y[i:i + L] += seg[:len(y[i:i + L])] * (0.6 + 0.4 * np.sin(2 * np.pi * 38 * t[i:i + L]))
        at += L / sr + rng.uniform(0.03, 0.12)
    return norm(y, 0.5)


def ev_dust(sr, rng):
    """먼지 · 재 · 가루 — 아주 작은 알갱이가 흩어지는 사각거림 (드문드문한 짧은 틱)."""
    n = int(sr * 2.0)
    y = np.zeros(n)
    for _ in range(int(40 + 40 * rng.random())):
        i = int(rng.random() * (n - 200))
        L = int(sr * rng.uniform(0.001, 0.004))
        y[i:i + L] += rng.standard_normal(L) * rng.uniform(0.2, 1)
    y = highpass(y, 3000, sr)
    return norm(y * env(n, sr, 0.3, 2.0, 'lin'), 0.5)


def ev_tap(sr, rng):
    """압정 · 단추 · 작은 쇠붙이 — 작고 높은 '톡'."""
    n = int(sr * 0.5)
    exc = np.zeros(n)
    exc[0] = 1.0
    if rng.random() < 0.5:
        exc[int(sr * rng.uniform(0.06, 0.12))] = 0.4
    f = 2400 + 2000 * rng.random()
    return norm(resonator_bank(exc, [f, f * 2.7, f * 5.1], [0.08, 0.05, 0.03], [1, 0.5, 0.25], sr))


def ev_heartbeat(sr, rng):
    """가슴 · 심장 · 맥박 — 쿵-쿵 두 번의 낮은 박동."""
    n = int(sr * 1.6)
    t = np.arange(n) / sr
    y = np.zeros(n)
    for off, g in ((0.05, 1.0), (0.32, 0.7)):
        tt = t - off
        m = tt >= 0
        fr = 55 + 20 * np.exp(-np.maximum(tt, 0) / 0.03)
        y[m] += g * np.sin(2 * np.pi * np.cumsum(fr[m]) / sr) * np.exp(-tt[m] / 0.09)
    return norm(lowpass(y, 300, sr), 0.7)


def ev_cloth(sr, rng):
    """가죽끈 · 매듭 · 소매 · 천 — 부드럽고 낮은 천 스침."""
    n = int(sr * 1.4)
    y = lowpass(rng.standard_normal(n), 1200, sr)
    e = np.zeros(n)
    for _ in range(int(3 + 3 * rng.random())):
        at, L = int(rng.random() * n * 0.8), int(sr * rng.uniform(0.1, 0.35))
        e[at:at + L] += np.hanning(L)[:len(e[at:at + L])]
    return norm(y * lowpass(e, 40, sr, 1), 0.5)


EVENT_SYNTH = {'wind': ev_wind, 'rain': ev_rain, 'snow': ev_snow, 'knock': ev_knock, 'door': ev_door,
               'alarm': ev_alarm, 'machine': ev_machine, 'clock': ev_clock, 'flow': ev_flow, 'fire': ev_fire,
               'glass': ev_glass, 'animal': ev_animal,
               'drip': ev_drip, 'electric': ev_electric, 'creak': ev_creak, 'rustle': ev_rustle,
               'crack': ev_crack, 'liquid': ev_liquid, 'ice': ev_ice, 'breath': ev_breath,
               'metal': ev_metal, 'thump': ev_thump, 'friction': ev_friction, 'presence': ev_presence,
               'touch': ev_touch, 'pen': ev_pen, 'dust': ev_dust, 'tap': ev_tap, 'heartbeat': ev_heartbeat,
               'cloth': ev_cloth}


def room_bed(bg, sr=SR, dur=20.0, seed=0):
    """배경 사진 → 방의 공기(룸톤). 어두울수록 저역, 깊을수록 낮은 방 모드, 윤곽이 촘촘할수록 잔결."""
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    bg = bg or {}
    dark, depth, edges = bg.get('dark', 0.5), bg.get('depth', 0.5), bg.get('edges', 0.3)
    luma, warm = bg.get('luma', 0.2), bg.get('warmth', 0.0)
    y = lowpass(brown(n, rng), 200 + 1800 * (1 - dark) + 600 * luma, sr) * (0.6 + 0.4 * dark)
    base = 35 + 50 * (1 - depth)                              # 깊은 공간일수록 방 모드가 낮다
    modes = [base * r for r in (1.0, 1.41, 1.73, 2.0, 2.45)]
    y += resonator_bank(rng.standard_normal(n) * 0.02, modes, [1.5] * 5, [1, .7, .5, .4, .3], sr) * (2 + 3 * dark)
    air = highpass(rng.standard_normal(n), 3000 + 2000 * (warm < 0), sr) * (0.02 + 0.08 * edges)
    y = y + air
    slow = 0.75 + 0.25 * np.sin(2 * np.pi * np.arange(n) / sr / (6 + 6 * rng.random()))
    return norm(y * slow, 0.6)
