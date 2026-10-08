"""4단계 · 렌더 — 고른 구성(3단계)으로 장면 소리를 정확히 D초로 만든다.

  ① 배치   조각을 시간 위에 놓는다 — 이야기 사건은 그 문장 자리에(꿈의 법칙 적용), 오브제는 이름이 나오는 문장 자리에,
           낱말 소리(손 스침 · 글씨 긁힘 …)는 그 낱말이 나오는 문장 자리에,
           그림 속 소리원은 그림 속 좌우 위치·거리대로, 바닥(룸톤)은 알갱이로 다시 짜서 장면 내내
  ② 혼합   층별 음량·밀도·폭은 3단계 진화가 고른 값
  ③ 작곡   배경 분위기 → 선법·화성 패드 · 4장면을 관통하는 동기 · 방의 공명 (composition.py)
  ④ 꿈의 변형  이질적 침입 · 음색 치환 · 변신 · 데자뷔 (dreamfx.py)
  ⑤ 공간   지속음 · 잔향(배경 깊이·장소) · 기승전결 음량 곡선 · 정적 문장 비우기 · 마스터

3단계는 ①②⑤만으로 '효과음 구성'을 평가하고(preview), 4단계가 그 위에 ③④를 얹는다.
시간은 전부 0~1(문장 위치) 또는 '초당'으로 적혀 있어서 D 가 몇 초든 같은 성격의 소리가 정확히 D초로 나온다.
렌더할 때 놓은 소리를 cues 에 그대로 적는다 → 해설 자료(guide.py)가 실제 소리와 어긋나지 않는다.
"""
import math
import os
import re

import numpy as np

from . import paths, synth

# ── 막(기승전결) 사전값 — 3팀 배경 엔진 index.html 의 AUDIO_ACTS 를 읽는다(배경 코드는 고치지 않음) ──
DEFAULT_ACTS = {   # index.html AUDIO_ACTS 의 사본 (10-05 기준)
    '기': {'hp': 60, 'lp': 900, 'wet': 0.60, 'long': 0.0, 'rate': 0.84, 'breathe': 0.35},
    '승': {'hp': 40, 'lp': 6000, 'wet': 0.45, 'long': 0.0, 'rate': 0.95, 'breathe': 0.10},
    '전': {'hp': 90, 'lp': 16000, 'wet': 0.85, 'long': 0.3, 'rate': 1.06, 'breathe': 0.22},
    '결': {'hp': 250, 'lp': 1200, 'wet': 1.00, 'long': 1.0, 'rate': 0.78, 'breathe': 0.40},
}
# 막이 정하는 것 (진화하지 않음): 곡선의 정점 · 꿈의 변형 세기 · 음악 세기
STAGE = {
    '기': {'arc_peak': 0.8, 'dream': 0.55, 'music': 0.6},
    '승': {'arc_peak': 0.5, 'dream': 0.6, 'music': 0.65},
    '전': {'arc_peak': 0.6, 'dream': 0.8, 'music': 0.7},
    '결': {'arc_peak': 0.15, 'dream': 0.5, 'music': 0.8},
}


def audio_acts():
    acts = {k: dict(v) for k, v in DEFAULT_ACTS.items()}
    try:
        txt = open(os.path.join(paths.BACKGROUND_DIR, 'index.html'), encoding='utf-8').read()
        block = re.search(r'const AUDIO_ACTS\s*=\s*\{(.*?)\n\};', txt, re.S).group(1)
        n = 0
        for m in re.finditer(r"'(기|승|전|결)'\s*:\s*\{([^}]*)\}", block):
            acts[m.group(1)].update({k: float(v) for k, v in re.findall(r'(\w+)\s*:\s*(-?[\d.]+)', m.group(2))})
            n += 1
        return acts, 'team3/background/index.html AUDIO_ACTS' if n == 4 else '내장값(일부만 읽음)'
    except (OSError, AttributeError):
        return acts, '내장값'


def stage_params(sc):
    """막·감정·법칙이 정하는 값 (진화 밖) — 전체 음높이(테이프 늘어짐) · 곡선 · 꿈 · 음악 세기."""
    a = sc['acts'][sc['stage']]
    st = dict(STAGE.get(sc['stage'], STAGE['기']))
    st['pitch'] = 12 * math.log2(a['rate']) - (1.0 if 'sink' in sc['law_keys'] else 0.0)   # 기 −3 · 승 −0.9 · 전 +1 · 결 −4.3 반음
    st['dream'] = float(np.clip(st['dream'] + 0.15 * sc['emotion']['arousal'], 0.35, 0.95))
    st['arc_depth'] = 0.5
    return st


# ── 도구 ────────────────────────────────────────────────────────────────
_IR, _WIN = {}, {}


def _ir(t60, sr, seed, damp):
    k = (round(t60, 1), sr, seed, round(damp, 1))
    if k not in _IR:
        if len(_IR) > 64:
            _IR.clear()
        _IR[k] = synth.reverb_ir(t60, sr, seed=seed, damp=damp)
    return _IR[k]


def _pan(y, p):
    a = (float(np.clip(p, -1, 1)) + 1) * math.pi / 4
    return np.stack([y * math.cos(a), y * math.sin(a)], axis=1)


def _add(out, y, start):
    n = len(out)
    if start >= n or start + len(y) <= 0:
        return
    s0, s1 = max(0, start), min(n, start + len(y))
    out[s0:s1] += y[s0 - start:s1 - start]


def _hann(n):
    w = _WIN.get(n)
    if w is None:
        if len(_WIN) > 4096:
            _WIN.clear()
        w = _WIN[n] = np.hanning(n).astype(np.float32)
    return w


def granular(srcs, D, sr, density, grain, spread, reverse, speed, pitch0, rng):
    """알갱이 합성 — 조각을 20~600ms 알갱이로 다시 짠다. 밀도가 '초당'이라 길이에 비례해 늘어난다."""
    n = int(round(D * sr))
    out = np.zeros(n, dtype=np.float32)
    srcs = [s for s in srcs if len(s) > sr * 0.3]
    if not srcs:
        return out
    count = max(1, int(density * D))
    times = (np.arange(count) + rng.random(count)) / density
    r = rng.random((count, 5))
    for j, t in enumerate(times):
        src = srcs[j % len(srcs)]
        gl = max(32, int(grain * sr * (0.7 + 0.6 * r[j, 0])) // 16 * 16)
        rate = 2 ** ((pitch0 + spread * (2 * r[j, 1] - 1)) / 12)
        need = int(gl * rate) + 2
        if len(src) <= need + 2:
            continue
        pos = int((t * speed * sr + j * 7919) % (len(src) - need - 1))
        seg = np.interp(np.arange(gl) * rate, np.arange(need), src[pos:pos + need]).astype(np.float32)
        if r[j, 2] < reverse:
            seg = seg[::-1]
        _add(out, seg * _hann(gl) * (0.5 + 0.5 * r[j, 3]), int(t * sr))
    return out


def place_times(count, D, positions, cluster, rng, accel=False):
    """사건 시각 — 글 속 위치(0~1) 둘레에 몰리게(cluster) · 층화 표집 · accel 이면 뒤로 갈수록 촘촘."""
    if count <= 0:
        return np.array([])
    grid = np.linspace(0, 1, 512)
    p = np.ones_like(grid)
    if positions:
        bump = sum(np.exp(-0.5 * ((grid - u) / 0.05) ** 2) for u in positions)
        p = (1 - cluster) + cluster * bump / (bump.mean() + 1e-9)
    if accel:
        p = p * (0.25 + 1.75 * grid)
    cdf = np.cumsum(p)
    cdf /= cdf[-1]
    q = (np.arange(count) + rng.random(count)) / count
    return np.sort(np.interp(q, cdf, grid) * D)


def anchored_times(count, D, positions, cluster, rng, accel=False):
    """근거 문장마다 한 번은 '그 문장 자리'에 반드시 놓고(닻), 나머지는 place_times 로 흩는다."""
    anchors = sorted(set(round(u, 3) for u in positions or []))[:max(0, count)]
    at = [min(D - 0.05, u * D + 0.25) for u in anchors]
    rest = place_times(count - len(at), D, positions, cluster, rng, accel)
    return np.sort(np.concatenate([np.array(at, dtype=float), rest]))


def arc(u, stage, peak, depth):
    """기승전결 곡선 — 기는 차오르고, 승은 머물고, 전은 정점을 치고, 결은 사라진다."""
    base = {'기': 0.55 + 0.45 * (u * u * (3 - 2 * u)),
            '승': 0.85 + 0 * u,
            '전': 0.55 + 0.45 * np.exp(-((u - peak) / 0.22) ** 2),
            '결': 1.0 - 0.7 * u ** 0.8}[stage]
    bump = np.exp(-((u - peak) / 0.3) ** 2)
    return base * (1 - 0.4 * depth + 0.4 * depth * bump)


IMPULSIVE = ('drip', 'crack', 'thump', 'rustle', 'creak', 'liquid', 'knock', 'glass', 'clock', 'door', 'rain', 'fire')
NEAR = 0.08          # 사건 시각이 근거 문장 위치에서 이만큼(장면 길이 비율) 안이면 '그 문장 때문'으로 적는다


def _why(sents, u):
    best = None
    for su, st in sents or []:
        d = abs(su - u)
        if d <= NEAR and (best is None or d < best[0]):
            best = (d, st, su)
    return (best[1], best[2]) if best else None


def count(rate_per_sec, D, rng):
    """초당 빈도 × 길이 → 개수. 확률적 반올림이라 어떤 길이에서도 기대 밀도가 같다
    (10-08: '최소 1개'로 올리던 방식은 8초 미리듣기에서 사건 종류가 많은 장면을 실제보다 붐비게 만들었다)."""
    x = max(0.0, rate_per_sec * D)
    return int(x) + int(rng.random() < x - int(x))


def _side(x):
    return '왼쪽' if x < -0.33 else ('오른쪽' if x > 0.33 else '가운데')


# ── ① 배치 ──────────────────────────────────────────────────────────────
def arrange(sc, P, mats, D, sr, rng, note):
    """조각 → 층별 스테레오 {'bed','object','event','seen'} (음량은 아직 1). note 로 놓은 소리를 적는다."""
    from .read import EVENT_NAME, EVENT_RATE
    n = int(round(D * sr))
    laws = set(sc['law_keys'])
    gp = sc['stage_p']['pitch']
    W = P['width']
    st = {k: np.zeros((n, 2), dtype=np.float32) for k in ('bed', 'object', 'event', 'seen')}

    # 바닥 — 룸톤을 알갱이로. 고역을 걷어 '쉬익' 대신 '웅' 하는 공기로 (10-07: 잡음의 주원인이었음)
    bed = granular(mats['bed'], D, sr, P['bed_density'], P['bed_grain'], P['bed_spread'], 0.1, 0.6, gp, rng)
    bed = synth.lowpass(bed / (np.sqrt(np.mean(bed ** 2)) + 1e-9) * 0.1, 2200, sr, 1)
    st['bed'] += _pan(bed, 0.0)
    note(0, D, 'bed', 'bed', '방의 공기(룸톤) · 알갱이 %.0f개/초' % P['bed_density'],
         why=('배경: ' + ' / '.join(sc.get('backgrounds') or ['(배경 묘사 없음)']), None), src='배경 사진 수치 → 룸톤 합성')

    # 오브제 — 이름이 나오는 문장 자리에서 두드림·문지름, 그리고 정체 소리(그림 인식)
    objs = sc['objects']
    for idx, o in enumerate(objs):
        clips = mats['object'].get(o['idx'], [])
        if not clips:
            continue
        pan = W * (-0.6 + 1.2 * idx / (len(objs) - 1) if len(objs) > 1 else 0.0)
        times = anchored_times(count(P['obj_rate'] / 10, D, rng), D, o['positions'], 0.75, rng)
        for j, t in enumerate(times):
            y = synth.pitch(clips[j % len(clips)], gp + o['pitch_offset'])
            soft = 'uneven' in laws and j % 2
            g = (0.25 if soft else 1.0) * (0.6 + 0.4 * rng.random()) * 0.5
            _add(st['object'], _pan(y * g, pan), int(t * sr))
            note(t, len(y) / sr, 'object', o['name'], '%s 울림' % o['name'], o.get('sentences'),
                 '매번 다른 크기(작게)' if soft else None, src='오브제 실루엣%s → 모달 합성' % (
                     ' + 재질 ' + o['features']['material'] if o['features'].get('material') else ''))
        dr = mats['drone'].get(o['idx'])
        if dr is not None and P['obj_drone'] > 0.2:
            for u0 in (o['positions'] or [0.5])[:4]:
                Lw = min(D * 0.25, 14.0)
                seg = granular([dr], Lw, sr, 8, 0.5, 0.3, 0.0, 0.5, gp, rng)
                seg = seg * _hann(len(seg)) * P['obj_drone'] * 0.6
                t0 = u0 * D - Lw / 2
                _add(st['object'], _pan(seg, pan * 0.5), int(t0 * sr))
                note(max(0.0, t0), Lw, 'object', o['name'], '%s 문지름(지속음)' % o['name'], o.get('sentences'),
                     why=_why(o.get('sentences'), u0), src='오브제 실루엣 → 모달 합성')
        idt = o.get('identity')
        iclips = mats['event'].get(idt['event'], []) if idt else []
        if iclips:                                     # 정체 소리 — 오브제 이름이 나오는 문장 자리에서만(최대 3번), 없으면 두 번
            k3 = min(3, len(times))                    # 두드림 수보다 많지 않게 — 짧은 미리듣기에서도 밀도가 같도록
            at = [u * D + 0.4 for u in sorted(set(o['positions'] or []))[:k3]] or list(times[:2])
            for j, t1 in enumerate(at):
                y = synth.pitch(iclips[j % len(iclips)], gp + 1.0 * (2 * rng.random() - 1))
                _add(st['seen'], _pan(y * 0.4 * (0.7 + 0.3 * rng.random()), pan), int(t1 * sr))
                note(t1, len(y) / sr, 'seen', idt['event'], '%s (%s의 정체: %s)' % (
                    EVENT_NAME.get(idt['event'], idt['event']), o['name'], idt['word']), o.get('sentences'),
                     src=idt['src'] + ' → 자체 합성')

    # 이야기 사건 — 문장 자리에, 꿈의 법칙(빨라짐·삼켜짐·먼저 옴·매번 다른 크기·낮아짐)과 함께.
    # 같은 소리원이 배경 그림에 보이면(형광등이 왼쪽 위) 그 자리(좌우)에서 들린다
    seen = {x['event']: x for x in sc.get('seen') or []}
    for k, e in sc['events'].items():
        clips = mats['event'].get(k, [])
        if not clips:
            continue
        rate = EVENT_RATE[k] / 10 * P['evt_rate'] * (0.5 + 1.5 * e['weight'])
        cnt = count(rate, D, rng)
        accel = 'accel' in laws and k in IMPULSIVE
        for j, t in enumerate(anchored_times(cnt, D, e['positions'], P['evt_cluster'], rng, accel)):
            semis = gp + 1.5 * (2 * rng.random() - 1) - (3 * t / D if 'sink' in laws else 0)
            y = synth.pitch(clips[int(rng.integers(0, len(clips)))], semis)
            lw = []
            if accel:
                lw.append('빨라지는 간격')
            if 'sink' in laws:
                lw.append('낮아지는 소리')
            if 'swallow' in laws and k in IMPULSIVE and j % 3 == 0:
                m = int(0.035 * sr)                       # 닿는 순간 삼켜진다 — 머리만 남기고 끊는다
                y = y[:m] * np.linspace(1, 0, min(m, len(y)))
                lw.append('삼켜지는 소리(닿는 순간 끊김)')
            start = int(t * sr)
            if 'reverse' in laws and k in IMPULSIVE and j % 2 == 0:
                y = y[::-1]                               # 소리가 원인보다 먼저 — 거꾸로 차오르다 그 순간에 끝난다
                start -= len(y)
                lw.append('원인보다 먼저(거꾸로 차오름)')
            soft = 'uneven' in laws and j % 2
            if soft:
                lw.append('매번 다른 크기(작게)')
            g = (0.25 if soft else 1.0) * (0.5 + 0.5 * rng.random()) * 0.4
            jit = float(rng.uniform(-0.8, 0.8))
            pan = W * (0.85 * seen[k]['x'] + 0.15 * jit if k in seen else jit)
            _add(st['event'], _pan(y * g, pan), start)
            note(start / sr, len(y) / sr, 'event', k, EVENT_NAME[k], e.get('sentences'), ' · '.join(lw) or None,
                 src='이야기 사건 → 자체 합성%s' % ((' · 위치: 그림 속 %s(%s)' % (seen[k]['word'], _side(seen[k]['x'])))
                                                  if k in seen else ''))

    # 낱말 소리 — 분류표에 없던 낱말(손 · 글씨 · 가슴 …)이 나오는 문장 자리에서 (문장마다 한 번, 최대 4번)
    #   개수는 길이에 비례시켜(75초 기준) 짧은 미리듣기에서도 촘촘함이 같게
    from .read import WORD_NAME
    for k, w in (sc.get('words') or {}).items():
        clips = mats['event'].get(k, [])
        if not clips:
            continue
        pos = sorted(set(w['positions']))[:4]
        nmax = count(len(pos) / 75.0, D, rng) if D < 60 else len(pos)
        for j, u0 in enumerate(pos[:nmax]):
            t = min(D - 0.1, u0 * D + 0.6 + 0.6 * rng.random())
            y = synth.pitch(clips[j % len(clips)], gp + 1.0 * (2 * rng.random() - 1))
            _add(st['event'], _pan(y * 0.3 * (0.7 + 0.3 * rng.random()), W * float(rng.uniform(-0.7, 0.7))), int(t * sr))
            note(t, len(y) / sr, 'word', k, '%s (\'%s\')' % (WORD_NAME.get(k, k), ' · '.join(w['words'][:2])),
                 w.get('sentences'), why=_why(w.get('sentences'), u0), src='이야기 낱말 → 자체 합성')

    # 그림 속 소리원 — 이야기에는 없지만 배경에 보이는 것(창문·시계·책장…)이 그 자리에서 낮게
    #   좌우 = 그림 속 가로 위치 · 거리 = 깊이 지도(멀수록 작고 먹먹하게) · 빈도는 이야기 사건의 절반 이하
    for x in seen.values():
        k = x['event']
        clips = mats['event'].get(k, [])
        if not clips or k in sc['events']:
            continue
        near = float(x.get('near', 0.5))
        cnt = count(EVENT_RATE.get(k, 1.0) / 10 * 0.45 * P['evt_rate'], D, rng)
        for j, t in enumerate(place_times(cnt, D, None, 0.0, rng)):
            y = synth.pitch(clips[j % len(clips)], gp + 1.0 * (2 * rng.random() - 1))
            if near < 0.6:
                y = synth.lowpass(y, 1200 + 9000 * near, sr, 1)
            _add(st['seen'], _pan(y * 0.4 * (0.25 + 0.75 * near) * (0.6 + 0.4 * rng.random()), W * x['x']), int(t * sr))
            note(t, len(y) / sr, 'seen', k, '%s (그림 속 %s)' % (EVENT_NAME.get(k, k), x['word']),
                 why=('배경 그림에서 본 것: "%s" — %s · %s' % (
                     x['label'], _side(x['x']), '가까이' if near > 0.6 else ('멀리' if near < 0.3 else '중간 거리')), None),
                 src='그림 인식(%s) → 자체 합성' % x.get('src', 'Florence-2'))
    return st


def mix(st, P):
    return (st['bed'] * P['bed_gain'] + st['object'] * (0.4 + 0.8 * P['obj_gain'])
            + st['event'] * (0.4 + 0.8 * P['evt_gain']) + st['seen'] * (0.3 + 0.9 * P['seen_gain']))


# ── ⑤ 공간 · 곡선 · 마스터 ────────────────────────────────────────────────
def space(dry, sc, P, D, sr, note):
    laws = set(sc['law_keys'])
    n = len(dry)
    u = np.arange(n) / max(1, n)
    mono = dry.mean(axis=1)
    t60, damp = P['space_t60'], P['space_damp']
    seed = int(sc['num'])
    if 'space_link' in laws:                        # 소리와 공간의 연동 — 장면이 갈수록 공간이 커진다
        wl = np.stack([synth.convolve(mono, _ir(t60 * 0.5, sr, seed, 0.5)), synth.convolve(mono, _ir(t60 * 0.5, sr, seed + 7, 0.5))], 1)
        wh = np.stack([synth.convolve(mono, _ir(t60 * 1.6, sr, seed + 1, 0.5)), synth.convolve(mono, _ir(t60 * 1.6, sr, seed + 8, 0.5))], 1)
        wet = wl * (1 - u[:, None]) + wh * u[:, None]
    else:
        wet = np.stack([synth.convolve(mono, _ir(t60, sr, seed, 0.5)), synth.convolve(mono, _ir(t60, sr, seed + 7, 0.5))], 1)
    wet = np.stack([synth.lowpass(wet[:, c], damp, sr) for c in range(2)], 1)
    dryf = np.stack([synth.lowpass(dry[:, c], min(16000, damp * 2.5), sr, 1) for c in range(2)], 1)
    pl = sc.get('place')
    note(0, D, 'space', 'space', '잔향 %.1f초%s' % (t60, ' → %.1f초로 커짐' % (t60 * 1.6) if 'space_link' in laws else ''),
         law='소리와 공간의 연동' if 'space_link' in laws else None,
         why=('배경 깊이 %.2f%s · 막 %s' % ((sc.get('bg') or {}).get('depth', 0.5),
                                          (' · 장소 ' + pl[1]) if pl else '', sc['stage']), None), src='잔향 계산')
    return dryf * (1 - 0.5 * P['space_wet']) + wet * P['space_wet'] * 1.4


def shape(y, sc, D, note):
    """기승전결 음량 곡선 + 정적 문장 비우기 → (y, 곡선)."""
    n = len(y)
    u = np.arange(n) / max(1, n)
    sp = sc['stage_p']
    A = arc(u, sc['stage'], sp['arc_peak'], sp['arc_depth'])
    if 'sink' in sc['law_keys']:
        A = A * (1 - 0.3 * u)
    for u0, stc in sc.get('silence_sents') or []:
        A = A * (1 - 0.65 * np.exp(-0.5 * ((u - u0) / 0.025) ** 2))
        note(max(0.0, u0 * D - 0.05 * D), 0.1 * D, 'silence', 'silence', '정적 — 소리를 비움',
             why=(stc, u0) if stc else None, src='음량 곡선')
    return y * A[:, None], A


def master(y, sc):
    rms = np.sqrt(np.mean(y ** 2)) + 1e-9
    y = y / rms * 0.08 * (0.71 if sc['stage'] == '결' else 1.0)     # 결만 −3dB (배경 엔진과 같은 방향)
    return (np.tanh(y / 0.9) * 0.9).astype(np.float32)


def _noter(cues, D):
    rec = cues is not None

    def note(t, dur, layer, key, name, sents=None, law=None, why=None, src=None, reason=None):
        if not rec:
            return
        w = why or _why(sents, t / D)
        cues.append({'t': round(float(t), 3), 'dur': round(float(dur), 3), 'layer': layer, 'key': key, 'sound': name,
                     'sentence': w[0] if w else None, 'sentence_u': round(w[1], 3) if w and w[1] is not None else None,
                     'law': law, 'src': src, 'reason': reason})
    return note


def preview(sc, P, mats, D, sr, seed=0):
    """3단계 평가용 — 배치·혼합·공간·곡선만 (작곡·꿈의 변형 없이). → (스테레오, 층별 모노 + 초당 놓인 소리 수)"""
    rng = synth.rng_for(sc['num'], seed, 'render')
    placed = [0]

    def note(t, dur, layer, key, name, *a, **k):     # 놓은 소리 개수만 센다 (붐비지 않음 점수용 · 지속음은 빼고)
        if layer in ('object', 'event', 'seen', 'word') and '문지름' not in name:
            placed[0] += 1
    st = arrange(sc, P, mats, D, sr, rng, note)
    y, _ = shape(space(mix(st, P), sc, P, D, sr, note), sc, D, note)
    stems = {k: v.mean(axis=1) for k, v in st.items()}
    stems['_per_sec'] = placed[0] / D
    return y, stems


def render(sc, P, mats, D, sr, seed=0, cues=None):
    """최종 — ①배치 ②혼합 ③작곡 ④꿈의 변형 ⑤공간·곡선·마스터 → 스테레오 (int(D·sr), 2)."""
    from . import composition, dreamfx
    rng = synth.rng_for(sc['num'], seed, 'render')
    note = _noter(cues, D)
    st = arrange(sc, P, mats, D, sr, rng, note)
    dry = mix(st, P)
    sp = sc['stage_p']
    Q = dict(P, music=sp['music'], dream=sp['dream'], arc_peak=sp['arc_peak'])
    composition.render(sc, Q, D, sr, rng, dry, _add,
                       lambda t, dur, kind, name, reason, sent: note(t, dur, 'music', kind, name, why=sent, reason=reason,
                                                                     src='작곡 (자체 합성)'))
    dreamfx.apply(sc, Q, mats, D, sr, rng, dry, _add,
                  lambda t, dur, kind, name, reason, sent: note(t, dur, 'dream', kind, name, why=sent, reason=reason,
                                                                src='꿈의 변형 (자체 합성)'))
    # 배경 지속음 — 작곡의 으뜸음에 맞춘 낮은 음 · 분위기가 어두울수록 불협(완전5도 → 단2도)
    m = sc['music']
    f = 440.0 * 2 ** ((m['root_midi'] + m['key_shift'] - 69) / 12)
    while f > 85:
        f /= 2
    while f < 40:
        f *= 2
    dis = float(np.clip(0.5 - 0.5 * sc['mood']['valence'], 0, 1))
    ratio = 1.5 + (1.0595 - 1.5) * dis
    n = len(dry)
    t = np.arange(n) / sr
    dro = sum(a * np.sin(2 * np.pi * fr * t + ph) for fr, a, ph in
              ((f, 1.0, 0), (f * 1.003, 0.7, 1.0), (f * ratio, 0.6, 2.0), (f * 2, 0.3, 0.5)))
    dro = synth.lowpass(dro, 500, sr) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.05 * t))
    dry += _pan(dro.astype(np.float32) * 0.03 * (0.4 + 0.4 * (sc.get('bg') or {}).get('dark', 0.5)), 0.0)
    note(0, D, 'drone', 'drone', '배경 지속음 %.0fHz · 음정비 %.3f' % (f, ratio),
         why=('작곡 으뜸음에 맞춤 · 분위기 정서가 %+.2f → %s' % (sc['mood']['valence'], '불협(단2도 쪽)' if dis > 0.5 else '협화(완전5도 쪽)'),
              None), src='수식 합성')
    y, A = shape(space(dry, sc, P, D, sr, note), sc, D, note)
    if cues is not None:
        cues.append({'arc': [round(float(x), 3) for x in A[::max(1, len(A) // 300)]], 'D': D})
    return master(y, sc)


def scene_view(scene, acts):
    """1·2단계 장면 → 렌더가 쓰는 정보만 (프로세스 사이에 넘기기 쉽게)."""
    from .read import split_sentences
    sc = {
        'num': scene['num'], 'stage': scene['stage'], 'title': scene['title'], 'emotion': scene['emotion'],
        'mood': scene['mood'], 'music': scene.get('music'), 'acts': acts,
        'events': {k: {'positions': e['positions'], 'weight': e['weight'], 'sentences': e.get('sentences')}
                   for k, e in scene['events'].items() if any(m['key'] == k for m in scene['pieces'])},
        'silence_sents': scene.get('silence_sents'),
        'law_keys': [l['key'] for l in scene['laws']], 'law_src': {l['key']: l['src'] for l in scene['laws']},
        'backgrounds': scene.get('backgrounds'),
        'story_sents': [[round(u, 3), st] for st, u in split_sentences(scene.get('story') or '')],
        'objects': [{k: o.get(k) for k in ('idx', 'name', 'positions', 'sentences', 'features', 'pitch_offset', 'identity')}
                    for o in scene['objects']],
        'bg': (scene.get('background') or {}).get('features') or {},
        'seen': scene.get('seen') or [],
        'words': {k: {kk: w[kk] for kk in ('name', 'words', 'positions', 'sentences')} for k, w in (scene.get('words') or {}).items()
                  if any(m['key'] == k for m in scene['pieces'])},
        'vision_mats': ((scene.get('vision') or {}).get('bg_materials') or [])[:3],
        'place': ((scene.get('vision') or {}).get('place') or [None])[0],
        'pieces': scene['pieces'],
    }
    sc['stage_p'] = stage_params(sc)
    return sc
