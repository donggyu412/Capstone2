"""
Step 8. 오픈엔디드 꿈 사운드 생성 엔진 (Open-Ended Dream Sound Generator)

위치: team1/src/step8_generate_sound.py
입출력 폴더: team1/output/

[INPUT]  assembled_blueprint.json  (Step 6: 장면별 사운드 키워드 + 원본_구간 + 전환 방식)
         keyword_pool.json         (Step 5: 전체 사운드 구간 → 음향 특징 기준값 보정용)
         원본 사운드 영상/음원      (1팀의 5분 일상 사운드 영상, --audio 로 지정 가능)
[OUTPUT] output/sound/scene1_기.wav … scene4_결.wav   장면별 꿈 효과음
         output/sound/trans_기-승.wav …              장면 전환 효과음
         output/sound/dream_soundtrack.wav           전체 이어 붙인 꿈 사운드
         output/sound/sound_blueprint.json           레시피 · 음향 특징 · 진화 계보
         output/sound/step8_archive_map.txt          장면별 MAP-Elites 격자

핵심 아이디어: 기존 음원을 그대로 잇지 않는다
  1) 분해   : 원본 구간을 20~500ms 알갱이(grain)로 쪼갠다
  2) 재조립 : 알갱이의 길이 · 밀도 · 음높이 · 재생 방향 · 읽는 속도를 '레시피'로 정해 새 소리를 짠다
              (그래뉼러 합성, granular synthesis)
  3) 진화   : 레시피를 변이 연산자로 바꿔 가며 MAP-Elites로 탐색한다 (Open-Ended)
  4) 심판   : 목표 감정의 음향 단서에 맞는가, 원본을 알아들을 수 있는가, 그대로 베끼지는 않았는가

v2 변경점 (v1: 음높이 과변형 · 흔들림 · 잡음 때문에 '외계인 목소리'처럼 들리고 원본을 알아들을 수 없음)
  - 레이어 역할 분리: 레이어 0 '기억 층'(긴 알갱이, 음높이 ±3반음, 흔들림 없음 → 원본을 알아들을 수 있음)
                      + 레이어 1~2 '꿈 층'(자유 변형, 음량은 기억 층보다 작게)
  - 알아듣기 점수: 결과의 각 순간이 원본 재료의 어떤 순간과 닮았는지(프레임별 스펙트럼 모양) 측정
                   품질 = 감정 0.4 + 알아듣기 0.4 + 적당히 달라짐 0.15 + 무음 방지 0.05, 선택 조건 알아듣기 ≥ 0.7
  - 잡음성 목표 · 가중치 낮춤, 찌그러뜨림 · 떨림 · 끊김 상한 축소
  - output/sound/sources/ 에 원본 재료를 함께 저장 → 원본과 결과를 나란히 비교해 들을 수 있음

Close-Ended 장치
  - 기억의 씨앗 소리 레이어는 반드시 1개 이상 포함 (텍스트의 '씨앗' 규칙과 동일)
  - 감정별 음향 목표값 (크기 · 밝기 · 사건 밀도 · 잡음성 · 다이내믹스)
    ※ 음악 감정 연구의 일반적 경향(각성↑ → 크고 빠르고 거칠게, 슬픔 → 작고 어둡고 느리게)을
       바탕으로 한 휴리스틱 목표값이다.
  - 원본 거리 목표 구간: 너무 똑같으면(복사) 감점, 너무 멀면(기억 상실) 감점
  - 텍스트 설계도의 '관계'가 초기 레시피를 편향 (크기역전 → 음높이 낮춤, 포함역전 → 큰 울림 …)

필요 설치
  pip install numpy scipy imageio-ffmpeg

실행 예 (Capstone2 폴더에서):
  python team1/src/step8_generate_sound.py --seed 2
  python team1/src/step8_generate_sound.py --audio "team1/video/일상소리.mp4"
"""
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    import numpy as np
    from scipy.io import wavfile
    from scipy.signal import fftconvolve, lfilter
except ImportError:
    sys.exit("[오류] numpy/scipy가 없습니다. venv에서 `pip install numpy scipy imageio-ffmpeg`를 실행하세요.")

SR = 22050              # 전체 처리 샘플레이트
PREVIEW_SEC = 2.0       # 진화 중 평가용 미리듣기 길이 (짧게 해서 빠르게)


# ======================================================================
# 1. 오디오 입출력
# ======================================================================
AUDIO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".wav", ".mp3", ".m4a", ".flac", ".ogg"}
PREFER = ("sound", "사운드", "소리", "일상", "audio", "sfx")


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        import shutil
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        sys.exit("[오류] ffmpeg를 찾을 수 없습니다. `pip install imageio-ffmpeg`를 실행하세요.")


def load_audio(path: Path, sr: int = SR) -> np.ndarray:
    cmd = [ffmpeg_exe(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        sys.exit(f"[오류] 오디오를 읽지 못했습니다: {path}\n{r.stderr.decode(errors='ignore')[:300]}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def find_audio(team_dir: Path) -> Path:
    cands = [p for p in team_dir.rglob("*")
             if p.is_file() and p.suffix.lower() in AUDIO_EXT and "output" not in p.parts]
    if not cands:
        sys.exit(f"[오류] {team_dir} 아래에서 음원/영상 파일을 찾지 못했습니다. --audio 로 경로를 지정하세요.")
    preferred = [p for p in cands if any(k in p.name.lower() for k in PREFER)]
    if len(preferred) == 1:
        return preferred[0]
    if len(cands) == 1:
        return cands[0]
    listing = "\n".join(f"   - {p.relative_to(team_dir.parent)}" for p in (preferred or cands))
    sys.exit("[오류] 음원 후보가 여러 개입니다. 사운드 타임테이블과 맞는 파일을 --audio 로 지정하세요.\n" + listing)


def save_wav(path: Path, y: np.ndarray, sr: int = SR):
    y = np.clip(y, -1.0, 1.0)
    wavfile.write(str(path), sr, (y * 32767).astype(np.int16))


def to_sec(t: str) -> float:
    parts = [float(x) for x in t.strip().split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def cut_span(audio: np.ndarray, span: str, sr: int = SR):
    a, b = span.split("-")
    i, j = int(to_sec(a) * sr), int(to_sec(b) * sr)
    j = min(j, len(audio))
    if j - i < sr // 4:
        return None
    y = audio[i:j].astype(np.float64)
    peak = np.max(np.abs(y)) or 1.0
    return y / peak * 0.9


# ======================================================================
# 2. 음향 특징 (Close-Ended 평가 기준)
# ======================================================================
FEATS = ["크기", "밝기", "사건밀도", "잡음성", "다이내믹스"]

# 감정별 음향 목표값 (0~1, 이 영화 사운드 전체 분포 기준의 상대값)
EMO_TARGET = {
    "놀람": [0.70, 0.65, 0.70, 0.35, 0.85],
    "공포": [0.60, 0.30, 0.55, 0.45, 0.65],
    "슬픔": [0.30, 0.25, 0.15, 0.30, 0.20],
    "기쁨": [0.55, 0.70, 0.50, 0.25, 0.40],
    "신뢰": [0.45, 0.50, 0.30, 0.25, 0.20],
    "기대": [0.50, 0.55, 0.50, 0.35, 0.50],
    "혐오": [0.50, 0.35, 0.40, 0.50, 0.50],
    "분노": [0.80, 0.60, 0.70, 0.50, 0.70],
}
EMO_WEIGHT = [1.0, 1.0, 1.0, 0.5, 1.0]     # 잡음성 가중치는 낮게 (잡음으로 감정을 흉내 내지 않도록)

_HANN = {}


def _frames(y: np.ndarray, n=1024, hop=512):
    if len(y) < n:
        y = np.pad(y, (0, n - len(y)))
    if n not in _HANN:
        _HANN[n] = np.hanning(n)
    fr = np.lib.stride_tricks.sliding_window_view(y, n)[::hop]
    return fr * _HANN[n]


BAND_EDGES = np.geomspace(60, SR / 2, 25)


def raw_features(y: np.ndarray, sr: int = SR) -> dict:
    fr = _frames(y)
    S = np.abs(np.fft.rfft(fr, axis=1)) + 1e-9
    freqs = np.fft.rfftfreq(fr.shape[1], 1 / sr)
    rms = np.sqrt(np.mean(fr ** 2, axis=1)) + 1e-9
    w = rms / rms.sum()
    centroid = float(np.sum(w * (S @ freqs) / S.sum(axis=1)))
    flat = float(np.sum(w * np.exp(np.mean(np.log(S), axis=1)) / np.mean(S, axis=1)))
    logS = np.log(S)
    flux = np.maximum(0, np.diff(logS, axis=0)).mean(axis=1) if len(logS) > 1 else np.zeros(1)
    thr = flux.mean() + flux.std()
    peaks = np.sum((flux[1:-1] > thr) & (flux[1:-1] > flux[:-2]) & (flux[1:-1] >= flux[2:])) if len(flux) > 2 else 0
    db = 20 * np.log10(rms)
    bands = []
    for lo, hi in zip(BAND_EDGES[:-1], BAND_EDGES[1:]):
        m = (freqs >= lo) & (freqs < hi)
        bands.append(np.log(np.mean(S[:, m] ** 2) + 1e-12) if m.any() else -27.6)
    bands = np.array(bands)
    bands = bands - bands.mean()
    return {"loud": float(20 * np.log10(np.mean(rms))), "bright": math.log2(max(centroid, 50) / 50),
            "onset": peaks / (len(y) / sr), "noise": math.sqrt(flat), "dyn": float(np.std(db)),
            "bands": bands / (np.linalg.norm(bands) + 1e-9)}


def band_frames(y: np.ndarray, sr: int = SR):
    """프레임별 24대역 스펙트럼 모양 (알아듣기 점수용). 무음 프레임은 표시"""
    fr = _frames(y)
    S = np.abs(np.fft.rfft(fr, axis=1)) ** 2 + 1e-12
    freqs = np.fft.rfftfreq(fr.shape[1], 1 / sr)
    B = np.stack([np.log(S[:, (freqs >= lo) & (freqs < hi)].mean(axis=1) + 1e-12)
                  for lo, hi in zip(BAND_EDGES[:-1], BAND_EDGES[1:])], axis=1)
    loud = B.max(axis=1)
    B = B - B.mean(axis=1, keepdims=True)
    B = B / (np.linalg.norm(B, axis=1, keepdims=True) + 1e-9)
    return B, loud


def recognizability(y: np.ndarray, src_bands: np.ndarray) -> float:
    """알아듣기 점수: 결과의 각 순간이 원본 재료의 어떤 순간과 얼마나 닮았나 (0~1)
    순서를 섞거나 늘여도 소리 자체가 원본이면 높고, 음높이를 크게 바꾸거나 잡음이 되면 낮다."""
    B, loud = band_frames(y)
    active = loud > loud.max() - 12          # 끊긴(무음) 구간 제외
    if active.sum() < 3:
        return 0.0
    sim = B[active] @ src_bands.T
    return float(np.clip(np.mean(sim.max(axis=1)), 0, 1))


class Scaler:
    """이 영화 사운드 전체(키워드 풀의 모든 구간)의 분포로 특징을 0~1로 보정"""
    KEYS = ["loud", "bright", "onset", "noise", "dyn"]

    def __init__(self, clips: list):
        vals = {k: [] for k in self.KEYS}
        for c in clips:
            for i in range(0, max(1, len(c) - int(PREVIEW_SEC * SR)), int(PREVIEW_SEC * SR)):
                f = raw_features(c[i:i + int(PREVIEW_SEC * SR)])
                for k in self.KEYS:
                    vals[k].append(f[k])
        self.lo = {k: float(np.percentile(v, 5)) for k, v in vals.items()}
        self.hi = {k: float(np.percentile(v, 95)) for k, v in vals.items()}

    def __call__(self, f: dict) -> np.ndarray:
        return np.array([np.clip((f[k] - self.lo[k]) / max(1e-9, self.hi[k] - self.lo[k]), 0, 1)
                         for k in self.KEYS])


# ======================================================================
# 3. 레시피 (유전체) + 그래뉼러 렌더러
# ======================================================================
@dataclass
class Layer:
    src: int            # 소리 재료 번호
    grain: float        # 알갱이 길이 (ms)
    density: float      # 초당 알갱이 수
    pitch: float        # 음높이 (반음)
    jitter: float       # 음높이 흔들림 (반음)
    speed: float        # 원본을 읽어 가는 속도 (1=원래 속도, 0=한 순간에 멈춤)
    reverse: float      # 알갱이를 거꾸로 재생할 확률
    gain: float         # 음량
    start: float        # 원본에서 읽기 시작하는 위치 (0~1)


# 레이어 0 = '기억 층': 원본을 알아들을 수 있게 (긴 알갱이, 음높이 ±3반음, 흔들림 거의 없음)
MEM_RANGES = {"grain": (250, 1200), "density": (1, 8), "pitch": (-3, 3), "jitter": (0, 0.3),
              "speed": (0.5, 1.2), "reverse": (0, 0.15), "gain": (0.6, 1), "start": (0, 1)}
# 레이어 1~2 = '꿈 층': 자유롭게 변형하되 기억 층보다 작게
DREAM_RANGES = {"grain": (30, 500), "density": (1, 40), "pitch": (-12, 7), "jitter": (0, 2),
                "speed": (0, 2), "reverse": (0, 1), "gain": (0.05, 0.55), "start": (0, 1)}
RANGES = DREAM_RANGES


@dataclass
class Recipe:
    layers: list
    lowpass: float = 1.0     # 0=아주 먹먹, 1=필터 없음
    reverb: float = 0.1      # 울림
    trem: float = 0.0        # 떨림 깊이
    trem_rate: float = 4.0   # 떨림 속도 (Hz)
    gate: float = 0.0        # 끊김: 소리가 뚝뚝 끊기는 정도 (갑작스러움 · 다이내믹스)
    gate_rate: float = 4.0   # 끊김 단위 (초당 몇 토막)
    drive: float = 0.0       # 찌그러뜨림: 거칠고 크게
    seed: int = 0            # 알갱이 배치 난수 (같은 레시피 = 같은 소리)
    lineage: list = field(default_factory=list)

    def clone(self):
        return Recipe([Layer(**asdict(l)) for l in self.layers], self.lowpass, self.reverb,
                      self.trem, self.trem_rate, self.gate, self.gate_rate, self.drive,
                      self.seed, list(self.lineage))


@dataclass
class Source:
    keyword: str
    span: str
    clip: np.ndarray
    seed: bool           # 기억의 씨앗 소리인가


_IR = {}


def impulse_response(size: float) -> np.ndarray:
    key = round(size, 1)
    if key not in _IR:
        n = int((0.3 + 2.2 * key) * SR)
        g = np.random.default_rng(7)
        t = np.arange(n) / SR
        ir = g.standard_normal(n) * np.exp(-t * (6.0 / (0.3 + 2.2 * key)))
        _IR[key] = ir / np.sqrt(np.sum(ir ** 2))
    return _IR[key]


def one_pole_lowpass(y: np.ndarray, amount: float) -> np.ndarray:
    if amount >= 0.98:
        return y
    fc = 150 * ((SR / 2 / 150) ** amount)
    a = math.exp(-2 * math.pi * fc / SR)
    y = lfilter([1 - a], [1, -a], y)
    return lfilter([1 - a], [1, -a], y)


def add_reverb(y: np.ndarray, amount: float) -> np.ndarray:
    if amount < 0.03:
        return y
    wet = fftconvolve(y, impulse_response(amount))[:len(y)]
    return (1 - 0.6 * amount) * y + amount * wet


def render(rc: Recipe, sources: list, dur: float) -> np.ndarray:
    N = int(dur * SR)
    out = np.zeros(N + int(1.5 * SR))      # 가장 긴 알갱이(1.2초)도 들어가게
    rng = np.random.default_rng(rc.seed)
    for L in rc.layers:
        src = sources[L.src].clip
        n = len(src)
        g = max(64, int(L.grain / 1000 * SR))
        win = np.hanning(g)
        count = min(400, rng.poisson(L.density * dur))
        norm = L.gain / math.sqrt(max(1.0, L.density * L.grain / 1000))
        for t0 in np.sort(rng.integers(0, N, count)):
            pos = int(L.start * n + L.speed * t0) % n
            r = 2 ** ((L.pitch + rng.normal(0, L.jitter + 1e-9)) / 12)
            read = max(2, int(g * r))
            seg = src[(pos + np.arange(read)) % n]
            grain = np.interp(np.linspace(0, read - 1, g), np.arange(read), seg)
            if rng.random() < L.reverse:
                grain = grain[::-1]
            out[t0:t0 + g] += grain * win * norm
    y = out[:N]
    y = one_pole_lowpass(y, rc.lowpass)
    y = add_reverb(y, rc.reverb)
    if rc.trem > 0.02:
        t = np.arange(N) / SR
        y = y * (1 - rc.trem * (0.5 + 0.5 * np.sin(2 * math.pi * rc.trem_rate * t)))
    if rc.drive > 0.02:
        k = 1 + 8 * rc.drive
        pk = np.max(np.abs(y)) or 1
        y = np.tanh(y / pk * k) / math.tanh(k)
    if rc.gate > 0.02:
        blk = max(64, int(SR / rc.gate_rate))
        nb = N // blk + 1
        keep = (rng.random(nb) >= rc.gate).astype(float)
        keep[0] = 1.0
        env = np.repeat(keep, blk)[:N]
        ramp = max(8, int(0.005 * SR))
        env = np.convolve(env, np.ones(ramp) / ramp, mode="same")
        y = y * env
    peak = np.max(np.abs(y))
    return y / peak * 0.95 if peak > 0.95 else y


# ======================================================================
# 4. 평가 (Close-Ended 심판)
# ======================================================================
@dataclass
class SceneCtx:
    role: str
    emotion: str
    relation: str | None
    sources: list
    src_feats: list          # 재료별 (보정 특징, 대역 모양)
    scaler: Scaler
    src_bands: np.ndarray = None   # 모든 재료의 프레임별 대역 모양 (알아듣기 점수용)


def evaluate(rc: Recipe, ctx: SceneCtx) -> dict:
    y = render(rc, ctx.sources, PREVIEW_SEC)
    raw = raw_features(y)
    f = ctx.scaler(raw)
    tgt = np.array(EMO_TARGET.get(ctx.emotion, [0.5] * 5))
    w = np.array(EMO_WEIGHT)
    emo = 1 - float(np.sum(w * np.abs(f - tgt)) / w.sum())
    recog = recognizability(y, ctx.src_bands)
    # 원본 거리: 쓰인 재료들의 전체 특징과 얼마나 달라졌나 (그대로 복사하면 0에 가까움)
    gains = {}
    for L in rc.layers:
        gains[L.src] = gains.get(L.src, 0) + L.gain
    tot = sum(gains.values()) or 1
    sf = sum(ctx.src_feats[i][0] * g for i, g in gains.items()) / tot
    dist = min(1.0, float(np.mean(np.abs(f - sf))) * 2)
    changed = max(0.0, 1 - abs(dist - 0.3) / 0.3)          # 조금은 달라져야 꿈 (복사 방지)
    alive = 0.0 if f[0] < 0.03 else 1.0
    quality = 0.4 * emo + 0.4 * recog + 0.15 * changed + 0.05 * alive
    return {"quality": quality, "emotion_fit": emo, "recog": recog, "origin_dist": dist,
            "feats": f, "bd": (dist, float(f[2]))}


# ======================================================================
# 5. 변이 연산자 (Open-Ended) + 복구 (Close-Ended)
# ======================================================================
def clamp_layer(L: Layer, ranges=RANGES):
    for k, (lo, hi) in ranges.items():
        setattr(L, k, float(min(hi, max(lo, getattr(L, k)))))


def repair(rc: Recipe, ctx: SceneCtx):
    """Close-Ended: 레이어 0은 기억 층(알아들을 수 있게), 나머지는 꿈 층(작게)"""
    rng = random.Random(rc.seed)
    rc.layers = rc.layers[:3] or [random_layer(rng, ctx, memory=True)]
    seeds = [i for i, s_ in enumerate(ctx.sources) if s_.seed]
    mem = rc.layers[0]
    mem.src = (seeds[0] if seeds else mem.src) % len(ctx.sources)       # 기억 층 = 씨앗 소리
    clamp_layer(mem, MEM_RANGES)
    mem.density = max(mem.density, 1.2 / (mem.grain / 1000))           # 알갱이가 끊기지 않게 겹침 유지
    mem.density = min(mem.density, 3.0 / (mem.grain / 1000))
    for L in rc.layers[1:]:
        L.src = L.src % len(ctx.sources)
        clamp_layer(L, DREAM_RANGES)
    rc.lowpass = min(1, max(0.15, rc.lowpass))
    rc.reverb = min(0.8, max(0, rc.reverb))
    rc.trem = min(0.4, max(0, rc.trem))
    rc.trem_rate = min(10, max(0.5, rc.trem_rate))
    rc.gate = min(0.5, max(0, rc.gate))
    rc.gate_rate = min(8, max(1, rc.gate_rate))
    rc.drive = min(0.4, max(0, rc.drive))


def random_layer(rng: random.Random, ctx: SceneCtx, src=None, memory=False) -> Layer:
    R = MEM_RANGES if memory else DREAM_RANGES
    pick = lambda k: rng.uniform(*R[k])
    return Layer(src=rng.randrange(len(ctx.sources)) if src is None else src,
                 grain=pick("grain"), density=pick("density"), pitch=pick("pitch") * (0.5 if not memory else 1),
                 jitter=pick("jitter") * 0.5, speed=pick("speed"), reverse=pick("reverse") * 0.5,
                 gain=pick("gain"), start=rng.random())


def random_recipe(rng: random.Random, ctx: SceneCtx) -> Recipe:
    layers = [random_layer(rng, ctx, memory=True)]
    if rng.random() < 0.7:
        layers.append(random_layer(rng, ctx))
    rc = Recipe(layers, lowpass=rng.uniform(0.6, 1), reverb=rng.uniform(0, 0.4),
                trem=rng.uniform(0, 0.15), trem_rate=rng.uniform(1, 6), seed=rng.randrange(1 << 30))
    # 텍스트 설계도의 '관계'가 첫 레시피를 편향한다 (이후는 진화가 자유롭게 바꿈)
    rel = ctx.relation
    dream = rc.layers[1] if len(rc.layers) > 1 else None
    if rel == "크기역전":
        rc.layers[0].pitch = -3                                # 거대해짐 → 살짝 낮게
        if dream: dream.pitch = -12                            # 꿈 층은 한 옥타브 아래 그림자
    elif rel == "포함역전":
        rc.reverb = max(rc.reverb, 0.6)                        # 무언가의 '안'에 들어간 울림
    elif rel == "합체" and len(ctx.sources) > 1:
        rc.layers = [rc.layers[0], random_layer(rng, ctx, src=1)]
        rc.layers[1].gain = 0.5                                # 두 소리가 한 몸
    elif rel == "공감각" and dream:
        dream.grain, dream.density, dream.pitch = 40, 30, 7   # 반짝이는 소리 입자
    elif rel == "재질치환":
        rc.lowpass = 0.4
    rc.lineage.append(f"초기({rel or '관계 없음'})")
    repair(rc, ctx)
    return rc


def op_shake(rc, rng, ctx):
    """흔들기: 레이어 하나의 파라미터 몇 개를 조금 바꾼다"""
    i = rng.randrange(len(rc.layers))
    L, R = rc.layers[i], (MEM_RANGES if i == 0 else DREAM_RANGES)
    for k in rng.sample(list(R), 2):
        lo, hi = R[k]
        setattr(L, k, getattr(L, k) + rng.gauss(0, (hi - lo) * 0.12))
    return "흔들기"


def op_layer_add(rc, rng, ctx):
    """겹치기(합체): 다른 소리 재료의 알갱이 층을 하나 더 쌓는다"""
    if len(rc.layers) >= 3:
        return None
    rc.layers.append(random_layer(rng, ctx))
    return "겹치기"


def op_layer_drop(rc, rng, ctx):
    """도태: 층 하나를 없앤다"""
    if len(rc.layers) <= 1:
        return None
    rc.layers.pop(rng.randrange(len(rc.layers)))
    return "도태"


def op_reverse(rc, rng, ctx):
    """뒤집기: 알갱이를 거꾸로 재생"""
    if len(rc.layers) < 2:
        return None
    L = rng.choice(rc.layers[1:])   # 꿈 층만
    L.reverse = 1 - L.reverse
    return "뒤집기"


def op_freeze(rc, rng, ctx):
    """멈추기/늘이기: 원본을 읽는 속도를 거의 0으로 → 한 순간이 길게 늘어진다"""
    i = rng.randrange(len(rc.layers))
    rc.layers[i].speed = rng.choice([0.5, 0.6, 1.2]) if i == 0 else rng.choice([0.0, 0.05, 0.15, 1.8])
    return "멈추기"


def op_octave(rc, rng, ctx):
    """크기 뒤집기: 한 옥타브 위/아래로 점프 (작아짐/거대해짐)"""
    if len(rc.layers) < 2:
        return None
    L = rng.choice(rc.layers[1:])   # 꿈 층만
    L.pitch += rng.choice([-12, 12])
    return "옥타브"


def op_shatter(rc, rng, ctx):
    """부수기: 알갱이를 잘게 쪼개고 많이 뿌린다"""
    if len(rc.layers) < 2:
        return None
    L = rng.choice(rc.layers[1:])   # 꿈 층만
    L.grain *= 0.4
    L.density *= 2.5
    return "부수기"


def op_space(rc, rng, ctx):
    """공간 바꾸기: 울림 · 먹먹함 · 떨림을 바꾼다"""
    k = rng.choice(["reverb", "lowpass", "trem"])
    setattr(rc, k, getattr(rc, k) + rng.gauss(0, 0.3))
    if k == "trem":
        rc.trem_rate = rng.uniform(1, 12)
    return f"공간({k})"


def op_gate(rc, rng, ctx):
    """끊기: 소리를 토막 내 갑자기 멈추고 터지게 한다 (놀람 · 공포의 다이내믹스)"""
    rc.gate = rng.uniform(0.2, 0.8) if rc.gate < 0.1 else rc.gate + rng.gauss(0, 0.2)
    rc.gate_rate = rng.uniform(1.5, 12)
    return "끊기"


def op_drive(rc, rng, ctx):
    """찌그러뜨리기: 소리를 눌러 거칠고 크게 만든다"""
    rc.drive = rc.drive + rng.gauss(0.3, 0.2)
    return "찌그러뜨리기"


def op_reseed(rc, rng, ctx):
    """다시 뿌리기: 같은 레시피로 알갱이 배치만 새로"""
    rc.seed = rng.randrange(1 << 30)
    return "다시뿌리기"


OPERATORS = [(op_shake, 5), (op_layer_add, 1.2), (op_layer_drop, 1), (op_reverse, 1), (op_freeze, 1),
             (op_octave, 1), (op_shatter, 1), (op_space, 2), (op_gate, 1.2), (op_drive, 1),
             (op_reseed, 0.8)]


def mutate(parent: Recipe, rng: random.Random, ctx: SceneCtx) -> Recipe:
    child = parent.clone()
    fns, ws = zip(*OPERATORS)
    for _ in range(1 if rng.random() < 0.6 else 2):
        tag = rng.choices(fns, ws)[0](child, rng, ctx)
        if tag:
            child.lineage.append(tag)
    child.lineage = child.lineage[-30:]
    repair(child, ctx)
    return child


def crossover(a: Recipe, b: Recipe, rng: random.Random, ctx: SceneCtx) -> Recipe:
    child = a.clone()
    if b.layers:
        child.layers.append(Layer(**asdict(rng.choice(b.layers))))
        rng.shuffle(child.layers)
    child.lineage.append("교배")
    repair(child, ctx)
    return child


# ======================================================================
# 6. MAP-Elites 탐색 (장면마다) + 선택
# ======================================================================
def cell_of(bd, bins):
    d, o = bd
    return min(bins - 1, int(d * bins)), min(bins - 1, int(o * bins))


def evolve_scene(ctx: SceneCtx, rng: random.Random, iters: int, bins: int, init: int = 40):
    archive, log = {}, []

    def insert(rc):
        ev = evaluate(rc, ctx)
        c = cell_of(ev["bd"], bins)
        if c not in archive or ev["quality"] > archive[c][1]["quality"]:
            archive[c] = (rc, ev)

    for _ in range(init):
        insert(random_recipe(rng, ctx))
    for it in range(1, iters + 1):
        el = list(archive.values())
        if rng.random() < 0.1 and len(el) > 1:
            (a, _), (b, _) = rng.sample(el, 2)
            insert(crossover(a, b, rng, ctx))
        else:
            insert(mutate(rng.choice(el)[0], rng, ctx))
        if it % max(1, iters // 5) == 0:
            qs = [e["quality"] for _, e in archive.values()]
            log.append({"iter": it, "coverage": len(archive), "best_q": round(max(qs), 3)})
    return archive, log


def select(archive, rng: random.Random, min_emo=0.55, min_recog=0.7, temperature=0.02):
    """Close-Ended 선택: 알아들을 수 있고(알아듣기 ≥ 0.7) 감정에 맞는 것 중 상위권에서 확률 선택"""
    items = list(archive.values())
    ok = [x for x in items if x[1]["emotion_fit"] >= min_emo and x[1]["recog"] >= min_recog]
    pool = ok or items
    pool.sort(key=lambda x: -x[1]["quality"])
    top = pool[:max(3, len(pool) // 5)]
    ws = [math.exp((x[1]["quality"] - top[0][1]["quality"]) / temperature) for x in top]
    rc, ev = rng.choices(top, ws)[0]
    return rc, ev, bool(ok)


def archive_map(archive, bins) -> str:
    lines = []
    for oi in reversed(range(bins)):
        row = [f"{archive[(di, oi)][1]['quality']:.2f}" if (di, oi) in archive else "  · "
               for di in range(bins)]
        lines.append(f"  사건밀도 {oi / bins:.2f}~ | " + " ".join(row))
    lines.append("                 " + " ".join(f"{i / bins:.2f}" for i in range(bins)) + "  ← 원본 거리")
    return "\n".join(lines)


# ======================================================================
# 7. 장면 전환 효과음 (텍스트 설계도의 전환 방식을 소리로)
# ======================================================================
def xfade_curves(n):
    t = np.linspace(0, 1, n)
    return np.cos(t * math.pi / 2), np.sin(t * math.pi / 2)


def sweep_lowpass(y: np.ndarray, start: float, end: float, block: int = 512) -> np.ndarray:
    """시간에 따라 먹먹해지거나(삼켜짐) 열리는 필터"""
    out = np.zeros_like(y)
    zi1 = zi2 = np.zeros(1)
    nb = max(1, len(y) // block + 1)
    for bi in range(nb):
        seg = y[bi * block:(bi + 1) * block]
        if not len(seg):
            break
        amt = start + (end - start) * bi / max(1, nb - 1)
        fc = 120 * ((SR / 2 / 120) ** amt)
        a = math.exp(-2 * math.pi * fc / SR)
        s1, zi1 = lfilter([1 - a], [1, -a], seg, zi=zi1)
        s2, zi2 = lfilter([1 - a], [1, -a], s1, zi=zi2)
        out[bi * block:bi * block + len(seg)] = s2
    return out


def render_transition(mode: str, A: Recipe, B: Recipe, ctxA: SceneCtx, ctxB: SceneCtx, sec: float):
    n = int(sec * SR)
    a = render(A, ctxA.sources, sec)
    b = render(B, ctxB.sources, sec)
    fo, fi = xfade_curves(n)
    if mode == "번짐":                       # 앞 소리가 울림으로 번져 다음 소리를 물들임
        y = add_reverb(a, 1.0) * fo + b * fi
    elif mode == "삼킴":                     # 앞 소리가 먹먹하게 삼켜졌다가, 다음 소리가 열리며 뱉어짐
        h = n // 2
        y = np.concatenate([sweep_lowpass(a[:h], 1.0, 0.05) * np.linspace(1, 0.2, h),
                            sweep_lowpass(b[h:], 0.05, 1.0) * np.linspace(0.2, 1, n - h)])
    elif mode == "뒤집힘":                   # 앞 소리가 거꾸로 감기며 안쪽에서 다음 소리가 나옴
        y = a[::-1] * fo + b * fi
    elif mode == "녹아내림":                  # 앞 소리가 낮아지고 느려지며 녹아내림
        melt = A.clone()
        for L in melt.layers:
            L.pitch -= 5
            L.speed *= 0.3
            L.jitter = 0
        m = render(melt, ctxA.sources, sec)
        y = (a * np.linspace(1, 0, n) + m * np.sin(np.linspace(0, math.pi, n))) * 0.7 + b * fi
    else:                                    # 공감각: 앞 소리가 잘게 반짝이는 입자가 되어 다음 공간을 지음
        spark = A.clone()
        for L in spark.layers:
            L.grain, L.density, L.pitch, L.jitter = 70, min(40, L.density * 2), L.pitch + 3, 0
        s = render(spark, ctxA.sources, sec)
        y = a * fo * 0.7 + s * np.sin(np.linspace(0, math.pi, n)) * 0.4 + b * fi
    peak = np.max(np.abs(y)) or 1
    return y / peak * 0.9 if peak > 0.9 else y


def wake_tail(last: np.ndarray, sec: float) -> np.ndarray:
    """깨어남: 마지막 소리가 멀어지며 울림만 남고 사라짐"""
    n = int(sec * SR)
    tail = add_reverb(np.concatenate([last[-n:], np.zeros(n)]), 1.0)[:2 * n]
    tail = sweep_lowpass(tail, 0.8, 0.1) * np.linspace(1, 0, 2 * n) ** 2
    return tail


def concat(parts: list, fade_sec: float = 0.3) -> np.ndarray:
    f = int(fade_sec * SR)
    out = parts[0].copy()
    for p in parts[1:]:
        fo, fi = xfade_curves(f)
        out[-f:] = out[-f:] * fo + p[:f] * fi
        out = np.concatenate([out, p[f:]])
    return out


# ======================================================================
# 8. 실행
# ======================================================================
def describe(rc: Recipe, ctx: SceneCtx) -> dict:
    return {"layers": [{"역할": "기억 층" if i == 0 else "꿈 층", "재료": ctx.sources[L.src].keyword, "원본_구간": ctx.sources[L.src].span,
                        "씨앗": ctx.sources[L.src].seed,
                        "알갱이_ms": round(L.grain), "초당_알갱이": round(L.density, 1),
                        "음높이_반음": round(L.pitch, 1), "음높이_흔들림": round(L.jitter, 1),
                        "읽기_속도": round(L.speed, 2), "역재생_확률": round(L.reverse, 2),
                        "음량": round(L.gain, 2)} for i, L in enumerate(rc.layers)],
            "먹먹함": round(1 - rc.lowpass, 2), "울림": round(rc.reverb, 2),
            "떨림": {"깊이": round(rc.trem, 2), "속도_Hz": round(rc.trem_rate, 1)},
            "끊김": {"정도": round(rc.gate, 2), "초당_토막": round(rc.gate_rate, 1)},
            "찌그러뜨림": round(rc.drive, 2), "seed": rc.seed}


def main():
    team_dir = Path(__file__).resolve().parent.parent
    output_dir = team_dir / "output"
    ap = argparse.ArgumentParser(description="Step 8: 오픈엔디드 꿈 사운드 생성")
    ap.add_argument("--blueprint", default=str(output_dir / "assembled_blueprint.json"))
    ap.add_argument("--pool", default=str(output_dir / "keyword_pool.json"))
    ap.add_argument("--audio", default=None, help="원본 사운드 영상/음원 (비우면 team1 폴더에서 자동 탐색)")
    ap.add_argument("--out-dir", default=str(output_dir / "sound"))
    ap.add_argument("--iters", type=int, default=500, help="장면당 진화 탐색 횟수")
    ap.add_argument("--bins", type=int, default=6)
    ap.add_argument("--scene-sec", type=float, default=8.0)
    ap.add_argument("--trans-sec", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    for p in (a.blueprint, a.pool):
        if not Path(p).exists():
            sys.exit(f"[오류] 파일이 없습니다: {p}")
    bp = json.loads(Path(a.blueprint).read_text(encoding="utf-8"))
    pool = json.loads(Path(a.pool).read_text(encoding="utf-8-sig"))
    audio_path = Path(a.audio) if a.audio else find_audio(team_dir)
    print(f"[Step 8] 원본 음원: {audio_path}")
    audio = load_audio(audio_path)
    print(f"[Step 8] 길이 {len(audio) / SR:.1f}초 @ {SR}Hz")

    # 음향 특징 보정: 이 영화의 모든 사운드 구간 분포
    spans = sorted({x["구간"] for x in pool["키워드"]["사운드"] if x.get("구간")})
    clips = [c for c in (cut_span(audio, s) for s in spans) if c is not None]
    if not clips:
        sys.exit("[오류] 키워드 풀의 사운드 구간을 음원에서 잘라내지 못했습니다. 음원 파일이 맞는지 확인하세요.")
    scaler = Scaler(clips)
    print(f"[Step 8] 음향 특징 기준 보정: 구간 {len(clips)}개")

    rng = random.Random(a.seed)
    random.seed(a.seed)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src_dir = out_dir / "sources"
    src_dir.mkdir(exist_ok=True)

    ctxs, chosen, report, maps = [], [], [], []
    for s in bp["scenes"]:
        sources = []
        for item in s["사운드"]:
            for sp in item.get("원본_구간", []):
                c = cut_span(audio, sp)
                if c is not None:
                    sources.append(Source(item["키워드"], sp, c, bool(item.get("씨앗"))))
        if not sources:
            print(f"   [경고] {s['역할']} 장면의 사운드 구간을 찾지 못해 전체 구간에서 재료를 가져옵니다.")
            sources = [Source("전체 사운드", sp, cut_span(audio, sp), False) for sp in spans[:3]]
        src_feats = [(scaler(raw_features(x.clip[:int(PREVIEW_SEC * SR)])),
                      raw_features(x.clip[:int(PREVIEW_SEC * SR)])["bands"]) for x in sources]
        src_bands = np.concatenate([band_frames(x.clip)[0] for x in sources], axis=0)
        ctx = SceneCtx(s["역할"], s["감정"], s["관계"]["유형"] if s.get("관계") else None,
                       sources, src_feats, scaler, src_bands)
        print(f"[Step 8] 장면 {s['장면']} ({s['역할']}·{s['감정']}) 재료 {len(sources)}개 → 진화 {a.iters}회 ... ",
              end="", flush=True)
        archive, log = evolve_scene(ctx, rng, a.iters, a.bins)
        rc, ev, ok = select(archive, rng)
        print(f"격자 {len(archive)}/{a.bins ** 2}, 감정적합 {ev['emotion_fit']:.2f}, "
              f"알아듣기 {ev['recog']:.2f}, 원본거리 {ev['origin_dist']:.2f}")
        for k, x in enumerate(sources):                                   # 비교 듣기용 원본 재료
            save_wav(src_dir / f"scene{s['장면']}_재료{k + 1}.wav", x.clip * 0.8)
        y = render(rc, sources, a.scene_sec)
        fname = f"scene{s['장면']}_{s['역할']}.wav"
        save_wav(out_dir / fname, y)
        ctxs.append(ctx)
        chosen.append((rc, y))
        maps.append(f"[장면 {s['장면']} {s['역할']}·{s['감정']}]\n" + archive_map(archive, a.bins))
        report.append({"장면": s["장면"], "역할": s["역할"], "감정": s["감정"], "파일": fname,
                       "재료": [{"키워드": x.keyword, "원본_구간": x.span, "씨앗": x.seed} for x in sources],
                       "레시피": describe(rc, ctx),
                       "음향_특징": {k: round(float(v), 3) for k, v in zip(FEATS, ev["feats"])},
                       "감정_목표": dict(zip(FEATS, EMO_TARGET.get(s["감정"], [0.5] * 5))),
                       "지표": {"감정_적합도": round(ev["emotion_fit"], 3), "알아듣기": round(ev["recog"], 3),
                              "원본_거리": round(ev["origin_dist"], 3),
                              "품질": round(ev["quality"], 3), "조건통과": ok},
                       "탐색": {"coverage": f"{len(archive)}/{a.bins ** 2}", "log": log},
                       "진화_계보": rc.lineage})

    # 전환 + 전체 사운드트랙
    parts, trans_report = [chosen[0][1]], []
    for i, t in enumerate(bp["transitions"]):
        ty = render_transition(t["방식"], chosen[i][0], chosen[i + 1][0], ctxs[i], ctxs[i + 1], a.trans_sec)
        fname = f"trans_{t['from']}-{t['to']}.wav"
        save_wav(out_dir / fname, ty)
        trans_report.append({"from": t["from"], "to": t["to"], "방식": t["방식"], "파일": fname})
        parts += [ty, chosen[i + 1][1]]
    parts.append(wake_tail(chosen[-1][1], 2.0))
    full = concat(parts)
    save_wav(out_dir / "dream_soundtrack.wav", full)

    (out_dir / "sound_blueprint.json").write_text(json.dumps(
        {"audio": str(audio_path.name), "sr": SR, "scenes": report, "transitions": trans_report,
         "soundtrack": {"파일": "dream_soundtrack.wav", "길이_초": round(len(full) / SR, 1)},
         "seed": a.seed}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "step8_archive_map.txt").write_text(
        "MAP-Elites 아카이브 (칸 값 = 품질, 가로 = 원본 거리 →, 세로 = 사건밀도 ↑)\n\n" + "\n\n".join(maps),
        encoding="utf-8")

    print()
    print(f"{'장면':<8}{'감정':<6}" + "".join(f"{k:>8}" for k in FEATS) + f"{'감정적합':>9}{'알아듣기':>9}")
    for r in report:
        feats = "".join(f"{r['음향_특징'][k]:>9.2f}" for k in FEATS)
        tgt = "".join(f"{r['감정_목표'][k]:>9.2f}" for k in FEATS)
        print(f"{r['장면']}.{r['역할']:<6}{r['감정']:<6}{feats}{r['지표']['감정_적합도']:>9.2f}{r['지표']['알아듣기']:>9.2f}")
        print(f"{'  (목표)':<14}{tgt}")
    print(f"\n[Step 8] 완료 → {out_dir / 'dream_soundtrack.wav'} ({len(full) / SR:.1f}초)")


if __name__ == "__main__":
    main()