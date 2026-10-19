"""4단계 ③ 작곡 — 배경의 분위기에 맞는 음악 (10-07 요청: 예술감 · 10-08: 배경 분위기를 따르게).

분위기 = 배경 그림(밝기·색온도·채도·대비 · 장소) 65% + 이야기 감정 35% → 정서가·각성 (read.mood).

세 가지를 장면마다 얹는다. 전부 자체 합성(외부 음원·모델 없음)이고, 이야기·이미지·감정에서 결정적으로 정한다.

  ① 화성 패드      분위기(정서가·각성)의 사분면 → 선법(mode), 막(기승전결) → 화음 진행.
                   화음이 바뀌는 자리 = 이야기 문장 경계 (글의 호흡에 맞춰 화성이 움직인다)
                     공포(부정·고각성) → 프리지아(♭2 의 불안) · 슬픔(부정·저각성) → 에올리안
                     기쁨(긍정·고각성) → 리디아 · 평온(긍정·저각성) → 이오니아
                   조성 계획: 기 = 으뜸 · 승 = 버금딸림(+5) · 전 = 나폴리(+1, 긴장) · 결 = 으뜸으로 돌아옴
  ② 동기(라이트모티프)  5음 동기 하나가 4장면을 관통하며 변형된다 — 기: 원형 / 승: 반복·한 칸 위로 /
                   전: 뒤집기·조각·빠르게·높게 / 결: 느리게 늘이기·낮게·마지막 음을 매달아 둠
                   울리는 자리 = 첫 오브제가 이야기에 나오는 문장 · 음색 = 그 오브제 실루엣의 모달 배음
                   (소리로 된 '기억의 주제' — 같은 오브제·같은 꿈을 귀로 이어 준다)
  ③ 방의 공명      효과음과 룸톤을 지금 화음의 음들에 맞춘 빗살 공명기에 통과 — 잡음이 화음으로 '노래'한다
                   (잡음성 바닥을 음악적 질감으로 바꾸는 장치 · 동정 공명/조율된 공명기)

근거 (PAPERS.md §7): 정서–선법·조성 — EMOPIA (Hung et al. 2021) 의 Russell 사분면 · Ferreira & Whitehead 2019 /
사운드스케이프 작곡 — Truax 2008† · 스펙트로모폴로지 — Smalley 1997† / 동기 발전 — 고전 작곡 기법.
세기는 막이 정한다(render.STAGE — 기 0.6 → 결 0.8, 뒤로 갈수록 음악이 앞으로).
"""
import math

import numpy as np
from scipy import signal

from . import synth

MODES = {
    'lydian': [0, 2, 4, 6, 7, 9, 11], 'ionian': [0, 2, 4, 5, 7, 9, 11], 'mixolydian': [0, 2, 4, 5, 7, 9, 10],
    'dorian': [0, 2, 3, 5, 7, 9, 10], 'aeolian': [0, 2, 3, 5, 7, 8, 10], 'phrygian': [0, 1, 3, 5, 7, 8, 10],
}
MODE_KO = {'lydian': '리디아', 'ionian': '이오니아(장조)', 'mixolydian': '믹솔리디아', 'dorian': '도리아',
           'aeolian': '에올리안(단조)', 'phrygian': '프리지아'}
PROG = {   # 막별 화음 진행(선법 안의 도수, 0 = 으뜸)
    '기': [0, 5, 3, 0],      # i  VI  iv  i   — 자리 잡기
    '승': [0, 3, 5, 4],      # i  iv  VI  v   — 움직임
    '전': [1, 6, 1, 4],      # ♭II VII ♭II v  — 긴장 (프리지아의 ♭2)
    '결': [5, 3, 0, 0],      # VI iv  i   i   — 돌아옴 (마지막은 9음을 얹어 매달아 둠)
}
KEY_PLAN = {'기': 0, '승': 5, '전': 1, '결': 0}
ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII']
NOTE = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
MOTIF_FORM = {'기': '원형', '승': '반복 · 한 칸 위로', '전': '뒤집기 · 조각 · 높고 빠르게', '결': '느리게 늘이기 · 낮게 · 매달린 끝음'}


def mode_for(emo):
    v, a = emo['valence'], emo['arousal']
    if v >= 0:
        return 'lydian' if a >= 0.15 else ('ionian' if a >= -0.2 else 'mixolydian')
    return 'phrygian' if a >= 0.15 else ('aeolian' if v < -0.3 else 'dorian')


def plan(scenes):
    """4장면 전체의 음악 계획 — 으뜸음(조성)과 동기는 꿈 전체가 공유한다. generate_sound 가 분석 직후 부른다.

    으뜸음: 첫 장면 배경 사진의 색온도 → 5도권 위의 자리 (따뜻할수록 ♯ 쪽, 차가울수록 ♭ 쪽 — 휴리스틱),
            밝기 → 음역 (어두운 꿈은 낮게)
    동기  : 첫 장면 첫 오브제(없으면 첫 배경 묘사) 이름에서 나온 시드 — 같은 스토리보드면 같은 동기."""
    first = scenes[0] if scenes else {}
    bg = (first.get('background') or {}).get('features') or {}
    warm = bg.get('warmth', 0.0)
    fifths = int(np.clip(round(warm * 20), -4, 4))            # −4(A♭) … +4(E)
    pc = (fifths * 7) % 12 + 9                                 # A(9) 둘레 — 어두운 장면에 어울리는 낮은 A 근처
    pc %= 12
    root_midi = 45 + ((pc - 9) % 12)                           # A2(45) ~ G#3
    if bg.get('luma', 0.2) < 0.18:
        root_midi -= 12 if root_midi > 50 else 0
    seed_name = ((first.get('objects') or [{}])[0].get('name') or (first.get('backgrounds') or ['꿈'])[0])
    rng = synth.rng_for('motif', seed_name)
    deg = [int(rng.choice([0, 2, 4]))]
    for _ in range(4):
        deg.append(int(np.clip(deg[-1] + rng.choice([-2, -1, 1, 2, 3]), -2, 7)))
    rhythm = [1.0, 0.5, 0.5, 1.0, 2.0]
    for s in scenes:
        s['music'] = {'root_midi': int(root_midi), 'mode': mode_for(s['mood']), 'motif': deg, 'rhythm': rhythm,
                      'motif_seed': seed_name, 'key_shift': KEY_PLAN.get(s['stage'], 0)}
    return {'root': NOTE[root_midi % 12], 'root_midi': int(root_midi), 'motif': deg, 'motif_seed': seed_name}


def _hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def degree_midi(root, mode, d):
    sc = MODES[mode]
    o, i = divmod(d, 7)
    return root + 12 * o + sc[i]


def chord(root, mode, d, seventh=False, add9=False):
    tones = [degree_midi(root, mode, d + k) for k in ((0, 2, 4, 6) if seventh else (0, 2, 4))]
    if add9:
        tones.append(degree_midi(root, mode, d + 8))
    return tones


def segments(D, story_sents, n):
    """화음 n 개의 경계 — 균등 분할 자리에 가장 가까운 '문장 시작' 위치로 붙인다(글의 호흡)."""
    starts = sorted(u for u, _ in (story_sents or []))
    b = [0.0]
    for k in range(1, n):
        target = k / n
        near = min(starts, key=lambda u: abs(u - target)) if starts else target
        b.append(near if abs(near - target) < 0.6 / n and near > b[-1] + 0.08 else target)
    b.append(1.0)
    return [(b[i] * D, b[i + 1] * D) for i in range(n)]


def _pad_voice(f, n, sr, rng, bright):
    t = np.arange(n) / sr
    y = np.zeros(n)
    for k in range(1, 5):
        fk = f * k
        if fk > sr / 2 - 500:
            break
        a = k ** -(2.4 - 1.2 * bright)
        for det in (-0.0018, 0.0021):                          # 두 목소리를 살짝 어긋나게 — 합창처럼 숨쉬는 결
            vib = 1 + 0.0025 * np.sin(2 * np.pi * (0.13 + 0.05 * rng.random()) * t + rng.random() * 6.28)
            y += a * np.sin(2 * np.pi * np.cumsum(fk * (1 + det) * vib) / sr + rng.random() * 6.28)
    return y


def _env(n, sr, att, rel):
    e = np.ones(n)
    a, r = min(n // 2, int(att * sr)), min(n // 2, int(rel * sr))
    if a:
        e[:a] = np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    if r:
        e[-r:] = np.cos(np.linspace(0, np.pi / 2, r)) ** 2
    return e


def _bell(f, dur, sr, feat, rng):
    """동기 한 음 — 오브제 실루엣의 모달 배음비로 울리는 종소리(이미지의 음색)."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    if feat and not feat.get('empty'):
        _, ratios, decays, amps = synth.modal_params(feat)
        ratios, amps = ratios[:5], amps[:5]
    else:
        ratios, amps = [1, 2.0, 2.76, 4.07], [1, 0.4, 0.25, 0.12]
    y = np.zeros(n)
    for r, a in zip(ratios, amps):
        if f * r < sr / 2 - 500:
            y += a * np.sin(2 * np.pi * f * r * t + rng.random() * 6.28) * np.exp(-t * (1.6 + 0.9 * r) / max(dur, 0.4))
    y *= np.minimum(1, t / 0.006)                               # 부드러운 망치
    return y


def motif_notes(m, stage):
    """동기의 막별 변형 → [(midi, 박 길이)]."""
    root = m['root_midi'] + m['key_shift'] + 24                # 동기는 두 옥타브 위
    deg, rh = list(m['motif']), list(m['rhythm'])
    if stage == '승':
        deg = [d + 1 for d in deg]                             # 반복진행 — 한 칸 위로
    elif stage == '전':
        deg = [deg[0] - (d - deg[0]) for d in deg][:3] * 2     # 뒤집기 + 앞 세 음 조각을 되풀이
        rh = [0.5, 0.5, 0.75] * 2
        root += 12
    elif stage == '결':
        rh = [r * 2 for r in rh]                               # 확대(느리게)
        root -= 12
        deg[-1] = deg[-1] + 1 if (deg[-1] % 7) == 0 else deg[-1]   # 으뜸으로 끝나지 않게 — 꿈은 닫히지 않는다
    return [(degree_midi(root, m['mode'], d), r) for d, r in zip(deg, rh)]


def _comb(x, d, fb):
    """되먹임 빗살 y[n] = x[n] + fb·y[n−d] — d 표본씩 묶어 한 번에 계산(lfilter 로 1000차 필터를 돌리면 수십 초 걸린다)."""
    n = len(x)
    pad = (-n) % d
    X = np.concatenate([x, np.zeros(pad)]).reshape(-1, d)
    Y = np.empty_like(X)
    prev = np.zeros(d)
    for k in range(len(X)):
        prev = X[k] + fb * prev
        Y[k] = prev
    return Y.reshape(-1)[:n]


def comb_bank(x, freqs, sr, fb=0.96, mix=1.0):
    """조율된 빗살 공명기 — 입력의 결을 freqs 의 음높이로 울리게 한다."""
    y = np.zeros_like(x)
    for f in freqs:
        d = max(2, int(round(sr / f)))
        y += _comb(x, d, fb) * (1 - fb)
    return y * mix / max(1, len(freqs))


def render(sc, P, D, sr, rng, dry, add, note):
    """작곡 층을 dry(스테레오)에 더한다. 화음 경계·동기 자리를 note 로 적는다."""
    m = sc.get('music')
    if not m:
        return
    amt = float(P.get('music', 0.6))
    n = int(round(D * sr))
    root = m['root_midi'] + m['key_shift']
    mode = m['mode']
    prog = PROG.get(sc['stage'], PROG['기'])
    segs = segments(D, sc.get('story_sents'), len(prog))
    luma = (sc.get('bg') or {}).get('luma', 0.25)                 # 밝은 배경 → 밝은 패드 음색
    bright = 0.5 * {'기': 0.3, '승': 0.5, '전': 0.75, '결': 0.25}.get(sc['stage'], 0.4) + 0.5 * float(np.clip(luma * 1.6, 0, 1))
    md = sc['mood']
    xf = min(2.5, D / 12)
    q = 4 if sr >= 32000 else 2                                 # 패드는 3.5kHz 아래뿐 — 1/q 표본율로 만들고 올린다(속도)
    srp = sr // q
    npad = int(round(D * srp))
    pad = np.zeros(npad)
    res_in = dry.mean(axis=1).copy()                           # 공명기에 넣을 것 = 지금까지의 효과음·룸톤
    res = np.zeros(n)
    sents = sc.get('story_sents') or []
    for i, ((t0, t1), dgr) in enumerate(zip(segs, prog)):
        last = (i == len(prog) - 1)
        tones = chord(root, mode, dgr, seventh=(sc['stage'] == '전'), add9=(last and sc['stage'] == '결'))
        a, b = max(0, int((t0 - xf / 2) * sr)), min(n, int((t1 + xf / 2) * sr))
        L = b - a
        if L < sr // 4:
            continue
        pa, pb = a // q, min(npad, b // q)
        Lp = pb - pa
        seg = np.zeros(Lp)
        for j, mt in enumerate(tones):
            mt = mt + 12 if mt < 48 else mt                    # 패드 음역 C3 위
            seg += _pad_voice(_hz(mt), Lp, srp, rng, bright) * (0.9 if j == 0 else 0.6)
        pad[pa:pb] += seg * _env(Lp, srp, xf, xf)
        # ③ 방의 공명 — 이 화음의 음들(아래 옥타브 포함)로 효과음을 울린다
        ftones = [_hz(t) for t in tones[:3]] + [_hz(tones[0] - 12)]
        res[a:b] += comb_bank(res_in[a:b], ftones, sr) * _env(L, sr, xf, xf)
        name = '%s %s %s(%s)' % (NOTE[root % 12], MODE_KO[mode], ROMAN[dgr % 7] if dgr >= 0 else '?',
                                '-'.join(NOTE[t % 12] for t in tones))
        su = next((u for u, _ in sents if abs(u * D - t0) < 0.5), None)
        st = next((s for u, s in sents if su is not None and u == su), None)
        note(t0, t1 - t0, '화성', name,
             '배경 분위기(정서가 %+.2f · 각성 %+.2f) → %s 선법 · 막 %s 진행 %d/%d%s' % (
                 md['valence'], md['arousal'], MODE_KO[mode], sc['stage'], i + 1, len(prog),
                                               ' · 이야기 문장 경계에서 화음이 바뀜' if su is not None else ''),
             (st, su) if st else None)
    pad = synth.lowpass(pad, min(900 + 2600 * bright, srp / 2 - 300), srp)
    pad = signal.resample_poly(pad, q, 1)[:n]
    if len(pad) < n:
        pad = np.pad(pad, (0, n - len(pad)))
    pad = pad / (np.sqrt(np.mean(pad ** 2)) + 1e-9) * 0.05 * amt
    add(dry, np.stack([pad * 0.95, pad * 1.0], 1).astype(np.float32), 0)
    res = res / (np.sqrt(np.mean(res ** 2)) + 1e-9) * 0.035 * amt
    add(dry, np.stack([res, res], 1).astype(np.float32), 0)

    # ② 동기 — 첫 오브제가 나오는 문장 자리에서 (없으면 1/4 · 3/5 자리)
    objs = sc.get('objects') or []
    o = objs[0] if objs else None
    pos = sorted(set((o.get('positions') or []) if o else []))
    if not pos:
        pos = [0.25, 0.6]
    pos = [u for u in pos if 0.04 < u < 0.92][:3] or [0.3]
    beat = 0.85 - 0.25 * max(0, sc['mood']['arousal'])            # 각성이 높은 배경일수록 동기가 빠르게
    notes = motif_notes(m, sc['stage'])
    feat = o.get('features') if o else None
    for k, u0 in enumerate(pos):
        t = u0 * D
        start = t
        for mt, r in notes:
            dur = r * beat
            y = _bell(_hz(mt), max(0.6, dur * 2.2), sr, feat, rng)
            pan = 0.35 * math.sin(k * 1.7 + mt)
            add(dry, synth_pan((y / (np.max(np.abs(y)) + 1e-9) * 0.22 * amt).astype(np.float32), pan), int(t * sr))
            t += dur
        st = next((s for uu, s in ((o.get('sentences') or []) if o else []) if abs(uu - u0) < 1e-3), None)
        note(start, t - start, '동기', '동기 — %s (%s)' % (MOTIF_FORM.get(sc['stage'], ''), '-'.join(NOTE[x % 12] for x, _ in notes)),
             '꿈 전체를 관통하는 5음 주제 · 음색은 "%s" 실루엣의 배음' % (o['name'] if o else '종'),
             (st, u0) if st else None)


def synth_pan(y, p):
    a = (p + 1) * math.pi / 4
    return np.stack([y * math.cos(a), y * math.sin(a)], axis=1)
