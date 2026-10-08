"""3단계 · 진화 — 조각들을 '어떻게 배치하고 섞을지'를 찾는다. 품질 = 듣기 좋은 정도.

■ 무엇을 찾나 — 구성 유전자 15개 (아래 GENES)
  층별 음량(바닥·오브제·이야기 사건·그림 속 소리) · 사건 빈도 · 문장 자리에 몰리는 정도 · 오브제 두드림 빈도 ·
  룸톤 알갱이 결 · 좌우 폭 · 잔향 길이·비율·흡음. 소리 조각 자체와 시각(문장 자리)은 1·2단계가 이미 정했다.
  작곡·꿈의 변형은 4단계에서 얹으므로 여기서는 '효과음 구성'만 평가한다(8초 미리듣기).

■ 품질 = 듣기 좋은 정도 8가지의 가중합 (각 0~1, listen())
  잡음 적음   스펙트럼 평탄도가 낮을수록 (쉬익·치익 대신 음이 있는 소리)
  날카롭지 않음 4kHz 위 에너지 비율 — 심리음향의 '날카로움'(sharpness) 어림
  탁하지 않음 귀의 감도(A 가중)로 본 250Hz 아래 비율이 지나치게 크지 않게 (웅웅 뭉개진 소리 대신 또렷하게)
  떨림 없음   음량 포락선의 20~150Hz 변조 비율 — '거칠기'(roughness) 어림 (ECMA-418-2 의 정의 대역)
  붐비지 않음 초당 '놓인' 소리 수 0.4~1.8 (텅 비지도, 쉴 새 없지도 않게 — 종이 넘김 같은 소리 안의 잔결은 세지 않음)
  층 균형     어느 층도 가장 큰 층보다 10dB 넘게 묻히지 않고, 바닥(룸톤)이 가장 크지 않게
  사건이 들림 앞소리(오브제·사건·그림 소리)가 바닥보다 4~14dB 위
  그림 부합   소리의 밝기(스펙트럼 중심)가 배경 사진 밝기에서 나온 목표 근처 (교차감각 대응)

■ 탐색 = MAP-Elites (Mouret & Clune 2015) — 격자(밝기 8 × 밀도 8)마다 가장 듣기 좋은 구성을 보관해
  서로 다른 성격의 좋은 후보를 동시에 키운다. 출발점 = 막(배경 엔진 AUDIO_ACTS)·배경 사진·장소에서 나온 사전값.
  시간 예산에 닿으면 그 자리에서 멈춘다(3분 안).
"""
import math

import numpy as np
from scipy import signal

from . import synth

GENES = [   # (이름, 하한, 상한, 로그 여부, 뜻)
    ('bed_gain',    0.0, 1.0,   0, '바닥(룸톤) 음량'),
    ('bed_density', 4.0, 40.0,  1, '룸톤 알갱이 밀도(개/초)'),
    ('bed_grain',   0.05, 0.5,  1, '룸톤 알갱이 길이(초)'),
    ('bed_spread',  0.0, 5.0,   0, '룸톤 알갱이 음높이 흩어짐(반음)'),
    ('obj_gain',    0.0, 1.0,   0, '오브제 음량'),
    ('obj_rate',    0.3, 5.0,   1, '오브제 울림 빈도(10초당)'),
    ('obj_drone',   0.0, 1.0,   0, '오브제 문지름(지속음) 비중'),
    ('evt_gain',    0.0, 1.0,   0, '이야기 사건 음량'),
    ('evt_rate',    0.3, 2.5,   1, '이야기 사건 빈도 배율'),
    ('evt_cluster', 0.0, 1.0,   0, '사건이 문장 자리에 몰리는 정도'),
    ('seen_gain',   0.0, 1.0,   0, '그림 인식 소리 음량'),
    ('width',       0.3, 1.0,   0, '좌우 폭'),
    ('space_t60',   0.5, 8.0,   1, '잔향 길이(초)'),
    ('space_wet',   0.05, 0.8,  0, '잔향 비율'),
    ('space_damp',  800, 14000, 1, '잔향 고역 흡음(Hz)'),
]
NG = len(GENES)
BINS = 8
PREVIEW_SR = 22050
PREVIEW_D = 8.0
WEIGHTS = {'smooth': 0.15, 'soft': 0.10, 'clear': 0.12, 'steady': 0.12, 'pace': 0.11, 'balance': 0.14, 'clarity': 0.11,
           'fit': 0.15}
LISTEN_KO = {'smooth': '잡음 적음', 'soft': '날카롭지 않음', 'clear': '탁하지 않음', 'steady': '떨림 없음', 'pace': '붐비지 않음',
             'balance': '층 균형', 'clarity': '사건이 들림', 'fit': '그림 부합'}


def decode(g):
    return {name: float(lo * (hi / lo) ** x if lg else lo + (hi - lo) * x)
            for x, (name, lo, hi, lg, _) in zip(np.clip(g, 0, 1), GENES)}


def encode(p):
    g = np.zeros(NG)
    for i, (name, lo, hi, lg, _) in enumerate(GENES):
        v = float(np.clip(p[name], min(lo, hi), max(lo, hi)))
        g[i] = math.log(v / lo) / math.log(hi / lo) if lg else (v - lo) / (hi - lo)
    return np.clip(g, 0, 1)


def prior(sc):
    """출발점 — 막(배경 엔진 값) · 배경 사진 · 장소 (Close-ended 사전값)."""
    a = sc['acts'][sc['stage']]
    bg = sc.get('bg') or {}
    p = {'bed_gain': 0.45, 'bed_density': 14, 'bed_grain': 0.18, 'bed_spread': 1.0 + 2 * bg.get('edges', 0.3),
         'obj_gain': 0.6, 'obj_rate': 1.5, 'obj_drone': 0.4,
         'evt_gain': 0.6, 'evt_rate': {'전': 1.4, '결': 0.6}.get(sc['stage'], 1.0), 'evt_cluster': 0.6,
         'seen_gain': 0.45, 'width': 0.8,
         'space_t60': 1.5 + 4.0 * a['long'] + 2.5 * bg.get('depth', 0.5),
         'space_damp': float(np.clip(a['lp'] * 3, 1500, 14000)),
         'space_wet': float(np.clip(a['wet'] * 0.6, 0.1, 0.75))}
    pl = sc.get('place')
    if pl:                                                       # 그림 인식이 알아낸 장소의 잔향·흡음 쪽으로 (확신만큼)
        from .vision import PLACE_ACOUSTICS
        t60, damp = PLACE_ACOUSTICS.get(pl[0], (None, 1.0))
        w = float(min(1.0, max(0.0, (pl[2] - 0.08) / 0.4)))
        if t60:
            p['space_t60'] = (1 - w) * p['space_t60'] + w * t60 * (0.7 + 0.6 * bg.get('depth', 0.5)) * (1 + a['long'])
            p['space_damp'] = float(np.clip(p['space_damp'] * damp ** w, 800, 14000))
    return encode(p)


# ── 듣기 좋은 정도 ───────────────────────────────────────────────────────
def features(y, sr):
    """모노 → 특징 (초당·평균으로만 재서 길이와 무관)."""
    y = np.asarray(y, dtype=np.float64)
    nfft, hop = 2048, 512
    if len(y) < nfft * 2:
        y = np.pad(y, (0, nfft * 2 - len(y)))
    frames = np.lib.stride_tricks.sliding_window_view(y, nfft)[::hop] * np.hanning(nfft)
    P = np.abs(np.fft.rfft(frames, axis=1)) ** 2 + 1e-12
    f = np.fft.rfftfreq(nfft, 1 / sr)
    tot = P.sum(axis=1)
    rms_db = 10 * np.log10(tot / nfft + 1e-12)
    loud = rms_db > (rms_db.max() - 45)
    w = np.where(loud, tot, 0) + 1e-12
    cen_hz = float(np.sum((P * f).sum(axis=1) / tot * w) / np.sum(w))
    flat = np.exp(np.mean(np.log(P), axis=1)) / np.mean(P, axis=1)
    hf = float(np.sum(P[:, f > 4000].sum(axis=1)) / np.sum(tot))
    # A 가중(귀의 감도 — IEC 61672) 으로 본 저역 비율: 귀에 '웅웅 뭉개짐'으로 들리는 정도
    f2 = np.maximum(f, 1.0) ** 2
    Aw = (12194 ** 2 * f2 ** 2) / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) * (f2 + 12194 ** 2))
    PA = P * Aw ** 2
    low_a = float(PA[:, f < 250].sum() / (PA.sum() + 1e-12))
    S = np.log(P)
    flux = np.maximum(0, np.diff(S, axis=0)).mean(axis=1)
    onsets = 0.0
    if len(flux) > 5:
        med = signal.medfilt(flux, 15)
        thr = med + 1.5 * np.median(np.abs(flux - np.median(flux))) + 0.05
        peaks, _ = signal.find_peaks(flux - thr, height=0, distance=max(1, int(0.06 * sr / hop)))
        onsets = len(peaks) / (len(y) / sr)
    # 거칠기 어림 — 1ms 포락선의 20~150Hz 변조 에너지 / 전체 변조 에너지
    e = np.abs(signal.hilbert(y[: min(len(y), sr * 4)]))
    e = signal.resample_poly(e, 1000, sr) if sr != 1000 else e
    E = np.abs(np.fft.rfft(e - e.mean())) ** 2
    fe = np.fft.rfftfreq(len(e), 1 / 1000)
    rough = float(E[(fe >= 20) & (fe <= 150)].sum() / (E[fe >= 0.5].sum() + 1e-12))
    return {
        'centroid_hz': round(cen_hz, 1),
        'centroid': round(float(np.clip(math.log2(max(cen_hz, 50) / 50) / math.log2(10000 / 50), 0, 1)), 4),
        'flatness': round(float(np.clip((math.log10(np.sum(flat * w) / np.sum(w) + 1e-9) + 4.5) / 4.2, 0, 1)), 4),
        'onsets': round(float(onsets), 3),
        'sharp': round(hf, 4),
        'rough': round(rough, 4),
        'low': round(float(np.sum(P[:, f < 250].sum(axis=1) / tot * w) / np.sum(w)), 4),
        'low_a': round(low_a, 4),
        'dynamics': round(float(np.clip(np.std(rms_db[loud]) / 20, 0, 1)) if loud.any() else 0.0, 4),
    }


def brightness_target(sc):
    """그림 부합의 목표 — 밝은 화면 → 밝은 소리 (명도–음높이 대응 · 오브제 밝기는 화풍상 흰 면이 많아 25%만).
    0.33 = 약 350Hz(어두운 화면) · 0.55 = 약 950Hz(밝은 화면) — 10-08 첫 실행에서 어두운 장면이 180Hz 로 뭉개져 올림"""
    bg = sc.get('bg') or {}
    L = bg.get('luma', 0.2)
    objs = [o['features'] for o in sc['objects'] if 'luma' in o['features']]
    oL = float(np.mean([o['luma'] for o in objs])) if objs else L
    shift = {'기': -0.06, '승': 0.0, '전': 0.06, '결': -0.08}.get(sc['stage'], 0)
    return float(np.clip(0.33 + 0.35 * (0.75 * L + 0.25 * oL) + 0.08 * bg.get('bright', 0) + shift, 0.25, 0.7))


def _db(x):
    return 10 * math.log10(float(np.mean(x ** 2)) + 1e-12)


def listen(y, stems, P, sr, target):
    """미리듣기 → (품질, 세부점수, 특징)."""
    f = features(y.mean(axis=1), sr)
    c = lambda x: float(np.clip(x, 0, 1))
    s = {'smooth': 1 - c((f['flatness'] - 0.30) / 0.30),
         'soft': 1 - c((f['sharp'] - 0.06) / 0.20),
         'clear': 1 - c((f['low_a'] - 0.35) / 0.35),
         'steady': 1 - c((f['rough'] - 0.08) / 0.30)}
    o = stems.pop('_per_sec', f['onsets'])                     # 초당 '놓인' 소리 수 (소리 안의 잔결은 세지 않음)
    f['placed_per_sec'] = round(float(o), 3)
    s['pace'] = c(o / 0.4) if o < 0.4 else (1.0 if o <= 1.8 else 1 - c((o - 1.8) / 2.5))
    gains = {'bed': P['bed_gain'], 'object': 0.4 + 0.8 * P['obj_gain'], 'event': 0.4 + 0.8 * P['evt_gain'],
             'seen': 0.3 + 0.9 * P['seen_gain']}
    lv = {k: _db(stems[k] * gains[k]) for k in stems if np.any(stems[k])}
    if len(lv) > 1:
        top = max(lv.values())
        s['balance'] = float(np.mean([1 - c((top - v - 10) / 15) for v in lv.values()])) - (0.3 if lv.get('bed') == top else 0)
        fg = [k for k in lv if k != 'bed']
        if 'bed' in lv and fg:
            d = 10 * math.log10(sum(10 ** (lv[k] / 10) for k in fg) + 1e-12) - lv['bed']
            s['clarity'] = 1 - c((abs(d - 9) - 5) / 10)
        else:
            s['clarity'] = 0.7
    else:
        s['balance'], s['clarity'] = 0.5, 0.5
    s['balance'] = c(s['balance'])
    s['fit'] = 1 - c(abs(f['centroid'] - target) / 0.25)
    q = sum(WEIGHTS[k] * s[k] for k in WEIGHTS)
    return round(float(q), 4), {k: round(v, 3) for k, v in s.items()}, f


def evaluate(g, sc, mats, target, seed=0):
    from .render import preview
    P = decode(g)
    y, stems = preview(sc, P, mats, PREVIEW_D, PREVIEW_SR, seed)
    return listen(y, stems, P, PREVIEW_SR, target)


def cell(f):
    cc = int(np.clip((f['centroid'] - 0.1) / 0.7 * BINS, 0, BINS - 1))
    o = int(np.clip((math.log(f['onsets'] + 0.1) - math.log(0.1)) / (math.log(8.1) - math.log(0.1)) * BINS, 0, BINS - 1))
    return cc, o


def search(sc, mats, iters=200, seed=0, deadline=None, log=print):
    """MAP-Elites → 아카이브 {칸: (품질, 유전체, 특징, 세부점수)}, 최고 품질 기록."""
    import time as _t
    rng = synth.rng_for(sc['num'], seed, 'evolve')
    center = prior(sc)
    target = brightness_target(sc)
    archive, hist = {}, []

    def insert(g):
        q, det, f = evaluate(g, sc, mats, target, seed)
        k = cell(f)
        if k not in archive or q > archive[k][0]:
            archive[k] = (q, g, f, det)
        hist.append(round(max(v[0] for v in archive.values()), 4))

    insert(center)                                               # 사전값 그 자체도 후보
    init = max(8, iters // 6)
    for _ in range(init - 1):
        insert(np.clip(center + rng.normal(0, 0.25, NG), 0, 1))
    for _ in range(iters - init):
        if deadline and _t.time() > deadline:
            log('    장면 %d: 시간 예산에 닿아 %d회에서 멈춤' % (sc['num'], len(hist)))
            break
        keys = list(archive.keys())
        p = archive[keys[int(rng.integers(0, len(keys)))]][1]
        if rng.random() < 0.2 and len(keys) > 1:                # 교차
            q2 = archive[keys[int(rng.integers(0, len(keys)))]][1]
            p = np.where(rng.random(NG) < 0.5, p, q2)
        child = np.where(rng.random(NG) < 0.3, p + rng.normal(0, 0.16, NG), p)   # 변이
        insert(np.clip(child, 0, 1))
    return archive, hist, target


def archive_map(archive):
    rows = ['      밀도 →  (초당 사건 수, 로그 8칸)']
    for cc in range(BINS - 1, -1, -1):
        line = '밝기%d ' % cc
        for o in range(BINS):
            line += (' %.2f' % archive[(cc, o)][0]) if (cc, o) in archive else '    ·'
        rows.append(line)
    return '\n'.join(rows)


def novelty_vec(f):
    return np.array([f['centroid'], math.log(f['onsets'] + 0.2) / 3, f['flatness'], f['dynamics'], f['low']])


def choose(archive, chosen_before, k=6):
    """최종 — 품질 상위 k개 중, 앞 장면들과 성격이 다를수록 조금 가산(장면 사이 다양성)."""
    cands = sorted(archive.items(), key=lambda kv: -kv[1][0])[:k]
    best, best_s, nov_b = None, -1e9, 0.0
    for i, (c, (q, g, f, det)) in enumerate(cands):
        nov = min((float(np.linalg.norm(novelty_vec(f) - v)) for v in chosen_before), default=0.0)
        s = q + 0.1 * min(nov, 1.0)
        if s > best_s:
            best, best_s, nov_b = (c, q, g, f, det, i + 1), s, nov
    return best, round(nov_b, 4)


def scene_job(job):
    """장면 하나: 2단계 재료 → 3단계 진화. 별도 프로세스에서 돈다(장면 4개를 CPU 코어에 나눠 동시에)."""
    import time as _t
    from . import pieces
    from .render import scene_view
    t0 = _t.time()
    s, run_dir = job['scene'], job['run_dir']
    logs = []
    pieces.build(s, run_dir, job['max_events'], job['seed'], log=logs.append)
    sc = scene_view(s, job['acts'])
    mats = pieces.load_all(sc, run_dir, PREVIEW_SR)
    lim = job.get('time_limit')
    archive, hist, target = search(sc, mats, job['iters'], job['seed'], (t0 + lim) if lim else None, log=logs.append)
    return {'num': s['num'], 'pieces': s['pieces'], 'view': sc, 'archive': archive, 'hist': hist, 'target': target,
            'archive_map': archive_map(archive), 'cells': len(archive), 'evals': len(hist),
            'sec': round(_t.time() - t0, 1), 'logs': logs}
