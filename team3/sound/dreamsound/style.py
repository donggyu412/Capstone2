"""스타일 — 입력(스토리보드 · 배경 · 오브제)과 출력(wav · 해설 자료)은 그대로 두고, 2·3·4단계의 수치와 규칙만 바꾼다.

  python team3/sound/generate_sound.py --style apichatpong

■ default      지금까지의 꿈 사운드 (기본값)
■ apichatpong  아피찻퐁 위라세타꾼 영화의 사운드 방식 — 근거 (PAPERS.md §12):
    · 사운드 디자이너 Akritchalerm Kalayanamitr 인터뷰 (Mankowski, MUBI Notebook, 2022)
        "주변 소리로 이야기를 한다. 음악보다 중요하다" · 귀뚜라미·새·공기·웅웅거림을 층으로 쌓는다 ·
        음량은 평평하게, 상한을 넘지 않게 · 중앙 아래 잔잔한 잡음 층 · 짧은 완전한 침묵 뒤 주변 소리가 돌아옴 ·
        선풍기·에어컨 같은 소리의 반복·변형('소리 시퀀스') · 〈메모리아〉의 굉음(감독의 폭발성 두부 증후군 경험)
    · Lovatt (2013)† — 환경 소리를 낯설 만큼 키워 기억의 질감을 만든다 · 반복·조각·수렴

  단계별로 바뀌는 것
    2 재료  그대로 — 렌더가 이 장면의 조각으로 주변 소리 층을 짠다 (10-16 · amb_source='derived'):
            반짝이는 결(짧은 사건 조각 → 2옥타브 위 · 촘촘하게 · 좁은 공명으로 벌레처럼 떨게) · 공기의 결(숨·냉기·종이 → 길게) ·
            낮은 웅웅거림(오브제 문지름 → 2옥타브 아래) · 소리 시퀀스 = 장면의 기계음, 없으면 오브제 울림
            (apichatpong_synth: 따로 합성한 밤 숲 소리 — 밤벌레 · 바람과 잎 · 웅웅거림 · 선풍기/형광등)
    3 진화  사건이 주변 소리와 비슷한 크기(−3~+3dB) · 초당 0.2~0.8개로 성기게 · 바닥이 가장 커도 감점 없음 ·
            '음량 고름'(다이내믹스가 작을수록) 항목 추가 · 출발점: 바닥 크게 · 사건 적게 · 폭 넓게 ·
            쓰는 값의 범위: 바닥 ≥ 0.6 · 사건 빈도 ≤ 0.7 · 오브제 울림 ≤ 10초당 1번 (10-16 강화)
    4 렌더  배경 음악(화성 패드 · 동기 · 지속음) 끔 → 장면마다 한 번 '먼 라디오'(장면 안의 음악)
            꿈의 변형: 이질적 침입 · 음색 치환 대신 ① 침묵의 틈 ② 깊은 쿵(꿈 전체에 한 번) ③ 소리 시퀀스 (변신 · 데자뷔는 그대로)
            그림자·정령이 나오는 문장에서도 '존재감' 소리를 내지 않음 — 이상한 존재가 아무렇지 않게 있다
            기승전결 음량 곡선을 거의 평평하게 (결 장면 끝 25%만 천천히 낮춤)
            느리고 불규칙하게 · 자연스럽게 (10-26 · natural): 초당 0.12~0.55개 · 사건 간격 감마 분포 · 소리마다 음높이·크기·거리를
            조금씩 다르게 · 바람·벌레 울음·알갱이 밀도는 주기 없는 1/f 잡음으로 출렁임 · 소리 시퀀스·라디오도 느리게 흔들리게
            주변 소리 층은 공간·잔향(막의 먹먹함)을 거치지 않는 별도 버스 · 장면 경계에서 8초 겹쳐 이음 (10-16 강화)
  apichatpong_deep  위와 같고 라디오 없음(음악 0) · 소리 시퀀스 28초 · 침묵의 틈 장면마다 2번
  스타일은 음악적 방식(아이디어)이라 저작권 대상이 아니고, 영화 소리를 샘플링하지 않으므로 '외부 음원 0개'는 그대로다.
"""
import math

import numpy as np

from . import synth

STYLES = {
    'default': {
        'name': '기본',
        'summary': '꿈 사운드 기본 방식 — 효과음 + 배경 분위기 작곡 + 꿈의 변형(이질적 침입 · 음색 치환 · 변신 · 데자뷔)',
        'amb': False, 'music': True, 'radio': False, 'drone': True, 'flat_arc': False, 'fx': 'default',
        'mute_presence': False, 'listen': {}, 'prior': {}, 'gene_bounds': {}, 'amb_xfade': None,
        'seq_len': 16.0, 'gaps_fixed': None,
    },
    'apichatpong': {
        'name': '아피찻퐁 위라세타꾼 스타일',
        'summary': '주변 소리가 이야기를 이끈다 — 밤벌레·바람·웅웅거림을 평평하게 깔고, 음악 대신 먼 라디오, '
                   '꿈의 변형은 침묵의 틈 · 깊은 쿵 · 소리 시퀀스',
        'amb': True, 'music': False, 'radio': True, 'drone': False, 'flat_arc': True, 'fx': 'apichatpong',
        'mute_presence': True,
        # 3단계 평가 기준 — 사건이 주변 소리 속에 묻히듯(−3~+3dB) · 성기게 · 고르게  (10-16 강화: 0~6dB → −3~+3dB)
        # 10-26 느리게: 초당 0.2~0.8개 → 0.12~0.55개
        'listen': {'clarity_center': 0.0, 'clarity_tol': 3.0, 'pace_lo': 0.12, 'pace_hi': 0.55, 'bed_top_ok': True,
                   'sharp_allow': 0.06, 'flat_allow': 0.10, 'even_weight': 0.10},
        # 10-16 강화: 진화가 주변 소리를 줄이지 못하게 · 효과음이 붐비지 않게 — 유전자가 쓰는 값의 범위를 좁힌다
        # 10-26 느리게: 사건 빈도 ≤ 0.7 → 0.4 · 오브제 울림 ≤ 10초당 1번 → 0.5번
        'gene_bounds': {'bed_gain': (0.6, 1.0), 'evt_rate': (0.3, 0.4), 'obj_rate': (0.3, 0.5)},
        # 10-26 불규칙 · 자연스럽게 — 소리가 '박자에 맞춰' 나오지 않게, 같은 소리가 똑같이 되풀이되지 않게
        #   ioi_shape     사건 사이 간격 ~ 감마 분포(모양 0.6 < 1): 몰렸다가 오래 비는 간격 (1 = 무작위 포아송, 고르게 나눈 기존 방식보다 불규칙)
        #   anchor_spread 근거 문장 자리에서 0.1~1.2초 늦게 (늘 0.25초 뒤에 '딱' 오지 않게)
        #   pitch_sd · gain_db · far_p  소리마다 음높이(±반음 0.3)·크기(표준편차 4dB)·거리(35%는 멀리서 먹먹하게)를 조금씩 다르게
        #   wander        알갱이 밀도·바람·벌레 울음이 느린 1/f 잡음을 따라 출렁임 (사인파 같은 주기 없이)
        #   seq_slow · seq_jitter  소리 시퀀스 박을 1.35배 느리게 · 박마다 ±15% 흔들림 · 가끔 한 박 쉼
        #   radio_beat · rubato    먼 라디오 박 0.42 → 0.52초 · 음마다 ±8% 늘고 줄음
        #   word_max · seen_max    낱말 소리는 낱말마다 4번 → 2번 · 오브제 정체 소리는 3번 → 2번까지 (느리게)
        'natural': {'ioi_shape': 0.6, 'anchor_spread': 1.2, 'pitch_sd': 0.3, 'gain_db': 4.0, 'far_p': 0.35,
                    'wander': 0.6, 'seq_slow': 1.35, 'seq_jitter': 0.15, 'radio_beat': 0.52, 'rubato': 0.08,
                    'word_max': 2, 'seen_max': 2},
        # 10-16 강화: 주변 소리 층은 막의 먹먹함(공간·잔향 처리)을 거치지 않고, 장면 경계에서 8초 겹쳐 이어진다
        'amb_xfade': 8.0,
        # 10-16: 주변 소리를 '장면 자기 재료'로 만든다 (derived) — 따로 합성한 밤 숲 소리(synth)는 apichatpong_synth 로 비교
        'amb_source': 'derived',
        'seq_len': 16.0, 'gaps_fixed': None,
        # 3단계 출발점 — 바닥(주변 소리) 크게 · 사건 적게 · 폭 넓게 · 잔향은 조금 덜 (트인 밤 공기)
        'prior': {'bed_gain': ('set', 0.78), 'evt_rate': ('mul', 0.45), 'evt_gain': ('set', 0.45),
                  'obj_rate': ('mul', 0.4), 'obj_gain': ('set', 0.45), 'seen_gain': ('set', 0.4),
                  'width': ('set', 1.0), 'space_wet': ('mul', 0.7)},
        'guide_render': '고른 구성으로 75초를 놓고, 주변 소리 층과 먼 라디오, 침묵의 틈 같은 꿈의 변형을 얹습니다.',
        'guide_music': '<b>♪ 먼 라디오</b> — 배경 음악(화성 패드·동기·지속음)은 끄고, 장면마다 한 번 장면 안 어딘가의 작은 스피커에서 '
                       '노래가 들립니다. 선율은 꿈 전체를 관통하는 5음 동기입니다.',
        'guide_dream': [('침묵의 틈', '모든 소리가 2~4초 완전히 멈췄다가 돌아온다'),
                        ('깊은 쿵', '꿈 전체에 한 번, 원인 없는 굉음'),
                        ('소리 시퀀스', '기계음 하나가 리듬처럼 되풀이되며 조금씩 낮고 먹먹해진다'),
                        ('변신', '한 소리가 몇 초에 걸쳐 다른 오브제의 소리로 바뀐다'),
                        ('데자뷔', '장면 앞에서 들린 소리가 뒤에서 느리게·거꾸로·멀리서 되돌아온다')],
        'rules': [
            ('주변 소리 층', '이 장면의 재료로 짠 반짝이는 결(짧은 사건 조각을 높고 촘촘하게) · 공기의 결(숨·냉기·종이를 길게) · '
                           '낮은 웅웅거림(오브제 문지름을 낮게)을 장면 내내 평평하게 깐다 — "주변 소리로 이야기를 한다". '
                           '음량은 0.6 아래로 내려가지 않고, 막의 먹먹함을 거치지 않아 또렷하며, 장면 경계에서 8초 겹쳐 끊기지 않는다'),
            ('사건은 작게 · 성기게', '사건이 주변 소리와 비슷한 크기(−3~+3dB) · 초당 0.2~0.8개 · 사건 빈도와 오브제 울림의 상한을 낮춤 — 대사처럼 작게 말하는 소리'),
            ('먼 라디오', '배경 음악 대신 장면 안 어딘가에서 들리는 작은 스피커의 노래 (꿈 전체의 5음 동기를 쓴다)'),
            ('침묵의 틈', '모든 소리가 2~4초 완전히 멈췄다가 주변 소리부터 돌아온다'),
            ('깊은 쿵', '꿈 전체에 단 한 번, 머릿속에서 울리는 듯한 굉음'),
            ('소리 시퀀스', '장면의 기계음(전기 험 등) — 없으면 오브제 울림 — 한 토막이 리듬처럼 되풀이되며 조금씩 변한다'),
            ('정령은 소리 없이', '그림자·형상이 나오는 문장에서도 소리를 바꾸지 않는다 — 이상한 존재가 아무렇지 않게 있다'),
            ('평평한 곡선', '기승전결 음량 곡선을 거의 평평하게 (결 장면 끝만 천천히 낮춤)'),
            ('느리고 불규칙하게', '초당 0.12~0.55개 · 낱말 소리는 낱말마다 2번까지 · 소리 사이 간격이 몰렸다 비었다 하고(감마 분포), 같은 소리도 매번 '
                               '음높이·크기·거리가 조금씩 다르다 · 바람·벌레 울음은 주기 없이 출렁인다 — 박자에 맞춘 듯한 인공적인 느낌을 없앤다'),
        ],
    },
}

# 더 진한 변형 — 소리 시퀀스를 길게(28초) · 침묵의 틈을 장면마다 2번 · 라디오 없이 (음악을 완전히 없앰 — 근거 자료에 더 가깝게)
STYLES['apichatpong_deep'] = dict(STYLES['apichatpong'], name='아피찻퐁 위라세타꾼 스타일 (진하게)',
                                  summary=STYLES['apichatpong']['summary'].replace('음악 대신 먼 라디오', '음악 없이') +
                                  ' · 소리 시퀀스 28초 · 침묵의 틈 장면마다 2번',
                                  radio=False, seq_len=28.0, gaps_fixed=2,
                                  rules=[r for r in STYLES['apichatpong']['rules'] if r[0] != '먼 라디오'] +
                                  [('음악 없음', '먼 라디오도 빼고 음악을 완전히 없앤다'),
                                   ('길게 · 분명하게', '소리 시퀀스 28초 · 침묵의 틈 장면마다 2번')],
                                  guide_music='<b>♪ 음악 없음</b> — 배경 음악도, 장면 안의 노래도 없습니다. 주변 소리와 효과음만으로 이야기합니다.',
                                  guide_render='고른 구성으로 75초를 놓고, 주변 소리 층과 침묵의 틈 같은 꿈의 변형을 얹습니다 (음악 없음).')

# 비교용 — 주변 소리를 따로 합성한 밤 숲 소리(밤벌레 · 바람과 잎 · 웅웅거림 · 선풍기/형광등)로 (10-16 첫 판 방식)
STYLES['apichatpong_synth'] = dict(STYLES['apichatpong'], name='아피찻퐁 위라세타꾼 스타일 (합성 밤 숲 소리)', amb_source='synth',
                                   summary=STYLES['apichatpong']['summary'] + ' · 주변 소리는 따로 합성한 밤 숲 소리',
                                   rules=[('주변 소리 층', '따로 합성한 밤벌레 합창 · 바람과 잎 · 낮은 웅웅거림을 장면 내내 깐다 (장면 재료와 무관)')] +
                                   [r for r in STYLES['apichatpong']['rules'] if r[0] != '주변 소리 층'])


def clamp(P, sty):
    """유전자가 쓰는 값을 스타일의 범위 안으로 (진화는 그대로 돌고, 실제로 쓰는 값만 좁힌다)."""
    P = dict(P)
    for k, (lo, hi) in (sty.get('gene_bounds') or {}).items():
        if k in P:
            P[k] = float(min(hi, max(lo, P[k])))
    return P


def get(x):
    """장면(sc) · 이름 · None → 스타일 설정."""
    name = x.get('style', 'default') if isinstance(x, dict) else (x or 'default')
    return STYLES.get(name, STYLES['default'])


def apply_prior(p, sty):
    for k, (op, v) in (sty.get('prior') or {}).items():
        p[k] = v if op == 'set' else p[k] * v
    return p


def natural(x):
    """스타일의 '불규칙 · 자연스럽게' 설정 (없으면 빈 dict = 기존 방식 그대로)."""
    return get(x).get('natural') or {}


def wander(n, sr, rng, hz=0.1, octaves=3):
    """느린 1/f 잡음 (−1~1 근처) — hz 부터 한 옥타브씩 빠른 매끈한 무작위 곡선을 1/2 씩 작게 더한다.
    사인파 합처럼 되풀이되는 주기가 없다 (자연의 바람·생물 소리의 출렁임은 1/f 에 가깝다)."""
    out = np.zeros(n)
    D = n / sr
    for o in range(octaves):
        f = hz * 2 ** o
        m = max(3, int(D * f) + 3)
        pts = rng.standard_normal(m)
        x = np.linspace(0, m - 2, n)
        i = x.astype(int)
        fr = x - i
        fr = fr * fr * (3 - 2 * fr)                                # 매끈한 보간
        out += (pts[i] * (1 - fr) + pts[i + 1] * fr) * 0.5 ** o
    return out / (np.std(out) + 1e-9) * 0.5


def pick(clips, last, rng):
    """조각 고르기 — 바로 앞과 같은 조각은 피한다 (같은 소리가 연달아 똑같이 나오면 기계처럼 들림)."""
    k = int(rng.integers(0, len(clips)))
    if len(clips) > 1 and k == last:
        k = (k + 1 + int(rng.integers(0, len(clips) - 1))) % len(clips)
    return k


# ── 2 재료: 주변 소리 조각 (전부 수식 합성) ─────────────────────────────────
def amb_insects(sr, rng, dur=10.0):
    """밤벌레 합창 — 귀뚜라미 여러 마리(3.5~6kHz 펄스열) + 매미 띠잡음의 느린 부풀음 + 먼 개구리 몇 번."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    y = np.zeros(n)
    for _ in range(int(rng.integers(4, 7))):                       # 귀뚜라미 — 마리마다 음높이·박자·자리가 다르다
        f = rng.uniform(3500, 6000)
        rate = rng.uniform(14, 38)                                 # 찌르르 떨림 (초당)
        chirp = rng.uniform(0.25, 0.7)                             # 한 번 우는 길이
        period = chirp + rng.uniform(0.2, 0.9)
        gate = ((t + rng.uniform(0, period)) % period) < chirp
        pulse = np.maximum(0, np.sin(2 * np.pi * rate * t)) ** 2
        y += rng.uniform(0.3, 1.0) * np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) * pulse * gate
    cic = synth.bandpass(rng.standard_normal(n), 4200, 6800, sr)  # 매미 — 띠잡음이 천천히 부풀었다 잦아듦
    swell = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.05, 0.12) * t + rng.uniform(0, 6))
    y += 0.6 * cic / (np.std(cic) + 1e-9) * 0.25 * swell * (0.6 + 0.4 * np.maximum(0, np.sin(2 * np.pi * 90 * t)))
    for _ in range(int(rng.integers(1, 3))):                       # 먼 개구리
        t0 = rng.uniform(0.5, dur - 1.0)
        i0, L = int(t0 * sr), int(0.35 * sr)
        tt = np.arange(L) / sr
        cro = np.sin(2 * np.pi * rng.uniform(180, 300) * tt) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 24 * tt))) * np.hanning(L)
        y[i0:i0 + L] += 0.5 * cro[:len(y[i0:i0 + L])]
    y = synth.lowpass(y, 7500, sr)
    return synth.norm(y, 0.8).astype(np.float32)


def amb_leaves(sr, rng, dur=10.0):
    """바람과 잎 — 넓은 띠잡음이 돌풍처럼 느리게 일렁이고, 가끔 잎이 스친다."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    base = synth.bandpass(rng.standard_normal(n), 300, 3000, sr)
    gust = sum(rng.uniform(0.3, 1) * np.sin(2 * np.pi * rng.uniform(0.03, 0.25) * t + rng.uniform(0, 6)) for _ in range(3))
    gust = 0.35 + 0.65 * (gust - gust.min()) / (np.ptp(gust) + 1e-9)
    leaf = synth.bandpass(rng.standard_normal(n), 2000, 6000, sr) * (rng.random(n) < 0.002).astype(float)
    leaf = np.convolve(leaf, np.hanning(int(0.03 * sr)), 'same')
    return synth.norm(base * gust + 0.4 * leaf, 0.7).astype(np.float32)


def amb_rumble(sr, rng, dur=10.0):
    """낮은 웅웅거림 — '중앙 아래 잔잔한 잡음 층'. 갈색 잡음을 120Hz 아래로."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    y = synth.lowpass(synth.brown(n, rng), 120, sr) * (0.8 + 0.2 * np.sin(2 * np.pi * 0.07 * t))
    return synth.norm(y, 0.8).astype(np.float32)


def amb_machine(sr, rng, kind='fan', dur=6.0):
    """기계음 — fan: 선풍기(날개 박자로 일렁이는 바람 + 모터 험) · hum: 형광등(120Hz 배음 지글거림)."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    if kind == 'hum':
        f0 = 120.0
        y = sum((1 / k) * np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6)) for k in range(1, 9))
        y = y * (0.85 + 0.15 * np.sign(np.sin(2 * np.pi * 60 * t))) + 0.15 * synth.bandpass(rng.standard_normal(n), 3000, 7000, sr)
    else:
        blade = rng.uniform(9, 13)                                 # 날개가 지나가는 박자
        air = synth.bandpass(rng.standard_normal(n), 250, 2500, sr) * (0.6 + 0.4 * np.sin(2 * np.pi * blade * t) ** 2)
        motor = sum((0.5 / k) * np.sin(2 * np.pi * rng.uniform(95, 110) * k * t) for k in range(1, 4))
        y = air + 0.4 * motor
    return synth.norm(y, 0.8).astype(np.float32)


def machine_kind(sc):
    ev = set((sc.get('events') or {}).keys()) | {x['event'] for x in sc.get('seen') or []}
    return 'hum' if 'electric' in ev else 'fan'


AMB_KO = {'insects': '밤벌레 합창', 'leaves': '바람과 잎', 'rumble': '낮은 웅웅거림', 'fan': '선풍기', 'hum': '형광등 험'}
AMB_LEVEL = {'insects': 0.55, 'leaves': 0.30, 'rumble': 0.45}


def loop(clips, D, sr, rng, xf=1.0):
    """조각들을 이어 붙여 D초짜리 끊김 없는 흐름으로 (1초씩 겹쳐 섞음)."""
    n = int(round(D * sr))
    out = np.zeros(n, dtype=np.float32)
    clips = [c for c in clips if len(c) > 2 * xf * sr]
    if not clips:
        return out
    x = int(xf * sr)
    pos, k = 0, int(rng.integers(0, len(clips)))
    while pos < n:
        c = clips[k % len(clips)]
        L = min(len(c), n - pos)
        w = np.ones(L, dtype=np.float32)
        a = min(x, L // 2)
        if a:
            w[:a] = np.linspace(0, 1, a)
            w[-a:] = np.linspace(1, 0, a)
        out[pos:pos + L] += c[:L] * w
        pos += max(1, len(c) - x)
        k += 1
    return out


# 장면 재료로 주변 소리 짜기 (derived) — 어떤 조각에서 왔는지 이름을 남긴다
SHIMMER_KEYS = ('drip', 'rustle', 'crack', 'glass', 'tap', 'pen', 'touch', 'dust', 'knock', 'creak', 'metal', 'clock',
                'rain', 'liquid', 'ice', 'snow', 'thump', 'friction', 'cloth')
AIR_KEYS = ('breath', 'ice', 'wind', 'flow', 'rain', 'snow', 'cloth', 'friction', 'rustle', 'liquid')
MACHINE_KEYS = ('electric', 'machine', 'alarm', 'clock')
AMB_KO.update({'shimmer': '반짝이는 결', 'air': '공기의 결', 'low': '낮은 웅웅거림'})
AMB_LEVEL.update({'shimmer': 0.45, 'air': 0.35, 'low': 0.45})


def _names(keys):
    from .read import EVENT_NAME, WORD_NAME
    return '·'.join((EVENT_NAME.get(k) or WORD_NAME.get(k) or str(k)) for k in keys[:3])


def _derived_streams(mats, D, sr, rng, sc):
    """→ [(키, 이름, 출처 설명, 만드는 함수)] — 장면 조각을 알갱이로 다시 짜서 주변 소리 층으로."""
    from .render import granular
    ev = mats.get('event') or {}
    out = []
    nat = natural(sc) if sc else {}
    wv = nat.get('wander', 0.0)
    sk = [k for k in SHIMMER_KEYS if ev.get(k)] or list(ev.keys())
    if sk:
        src = [c for k in sk for c in ev[k]]
        def shimmer():                                             # 짧은 조각을 2옥타브 올려 초당 70개 → 좁은 공명 몇 개로 울리고 빠르게 떨게 — 벌레 울음 같은 결
            n = int(round(D * sr))
            y = granular(src, D, sr, 70, 0.035, 4.0, 0.3, 1.0, 24, rng, wander=wv)
            t = np.arange(n) / sr
            z = np.zeros(n)
            for _ in range(4):                                     # 마리마다: 고유 음높이(좁은 공명) · 떨림 박자 · 우는 구간
                f = rng.uniform(3200, min(6500, sr / 2 - 800))
                band = synth.bandpass(y, f * 0.97, f * 1.03, sr)
                r0 = rng.uniform(16, 36)
                per = rng.uniform(0.6, 1.6)
                duty = rng.uniform(0.4, 0.75)
                if wv:                                             # 자연스럽게: 떨림 박자가 천천히 흔들리고, 우는 길이·쉬는 길이가 매번 다르며, 가끔 몇 초 멈춘다
                    ph = 2 * np.pi * np.cumsum(r0 * (1 + 0.12 * wander(n, sr, rng, 0.15))) / sr
                    pulse = np.maximum(0, np.sin(ph)) ** 2
                    gate = np.zeros(n)
                    i = int(rng.uniform(0, per) * sr)
                    while i < n:
                        on = int(per * duty * rng.lognormal(0, 0.35) * sr)
                        gate[i:i + on] = 1
                        off = per * (1 - duty) * rng.lognormal(0, 0.5)
                        if rng.random() < 0.12:
                            off += rng.uniform(2.0, 6.0)
                        i += on + int(off * sr)
                    gate = np.convolve(gate, np.hanning(int(0.02 * sr)) / (0.01 * sr), 'same')
                    lvl = np.clip(1 + 0.5 * wander(n, sr, rng, 0.05), 0.2, 2.0)
                else:
                    pulse = np.maximum(0, np.sin(2 * np.pi * r0 * t)) ** 2
                    gate = ((t + rng.uniform(0, per)) % per) < per * duty
                    lvl = 1.0
                z += band / (np.std(band) + 1e-9) * pulse * gate * lvl * rng.uniform(0.5, 1.0)
            return z + 0.15 * synth.bandpass(y, 2500, min(9000, sr / 2 - 500), sr) / (np.std(y) + 1e-9)
        out.append(('shimmer', AMB_KO['shimmer'], _names(sk) + ' 조각을 높고 촘촘하게', shimmer))
    ak = [k for k in AIR_KEYS if ev.get(k)]
    asrc = [c for k in ak for c in ev[k]] or list(mats.get('bed') or [])
    if asrc:
        def air():                                                 # 길게 늘여 느리게 일렁이게 — 바람 같은 공기
            n = int(round(D * sr))
            y = granular(asrc, D, sr, 10, 0.45, 1.5, 0.2, 0.3, -5, rng, wander=wv)
            y = synth.bandpass(y, 250, 3000, sr)
            t = np.arange(n) / sr
            if wv:                                                 # 자연스럽게: 주기 없는 돌풍 (느린 1/f 잡음)
                gust = wander(n, sr, rng, 0.025, 4)
            else:
                gust = sum(rng.uniform(0.3, 1) * np.sin(2 * np.pi * rng.uniform(0.03, 0.2) * t + rng.uniform(0, 6)) for _ in range(3))
            return y * (0.35 + 0.65 * (gust - gust.min()) / (np.ptp(gust) + 1e-9))
        out.append(('air', AMB_KO['air'], (_names(ak) if ak else '룸톤') + ' 조각을 길게 늘여', air))
    drones = list((mats.get('drone') or {}).values()) or list(mats.get('bed') or [])
    if drones:
        def low():                                                 # 오브제 문지름을 2옥타브 내려 저역만
            y = granular(drones, D, sr, 6, 0.6, 0.5, 0.0, 0.4, -24, rng, wander=wv)
            y = synth.lowpass(y, 150, sr)
            return y * np.clip(1 + 0.25 * wander(len(y), sr, rng, 0.04), 0.5, 1.5) if wv else y
        objn = [o['name'] for o in (sc or {}).get('objects', [])][:2]
        out.append(('low', AMB_KO['low'], ('오브제(%s) 문지름을 낮게' % '·'.join(objn)) if objn and mats.get('drone') else '룸톤을 낮게', low))
    return out


def amb_layer(mats, D, sr, rng, sc=None):
    """주변 소리 층(스테레오) → (스테레오, [(키, 이름)]). 좌우는 서로 다른 흐름으로(넓게), 웅웅거림은 가운데.
    음량은 바닥(룸톤)과 같은 기준(0.1 RMS × 종류별 비율)이고, 렌더가 바닥 음량을 곱한다.
    스타일의 amb_source: derived = 이 장면의 재료로 짬 (기본) · synth = 따로 합성한 밤 숲 소리."""
    n = int(round(D * sr))
    out = np.zeros((n, 2), dtype=np.float32)
    made = []
    src = get(sc or {}).get('amb_source', 'derived') if sc else 'synth'
    if src == 'derived':
        q = 2 if sr >= 44100 else 1                                # 주변 소리는 9kHz 아래뿐 — 절반 표본율로 짜고 올린다 (렌더 속도)
        sr2 = sr // q
        m2 = mats
        if q > 1:
            from scipy import signal as _sg
            dn = lambda c: _sg.resample_poly(c, 1, q).astype(np.float32)
            m2 = {'event': {k: [dn(c) for c in v] for k, v in (mats.get('event') or {}).items()},
                  'drone': {k: dn(v) for k, v in (mats.get('drone') or {}).items()},
                  'bed': [dn(c) for c in mats.get('bed') or []]}
        for k, nm, how, fn in _derived_streams(m2, D, sr2, rng, sc):
            ch = [fn() for _ in range(1 if k == 'low' else 2)]
            if q > 1:
                from scipy import signal as _sg
                ch = [_sg.resample_poly(c, q, 1)[:n] for c in ch]
                ch = [np.pad(c, (0, n - len(c))) for c in ch]
            ch = [c / (np.sqrt(np.mean(c ** 2)) + 1e-9) * 0.1 * AMB_LEVEL[k] for c in ch]
            out += (np.stack([ch[0], ch[-1]], 1) * (0.7071 if k == 'low' else 1.0)).astype(np.float32)
            made.append((k, '%s ← %s' % (nm, how)))
        return out, made
    for k in ('insects', 'leaves', 'rumble'):
        clips = (mats.get('amb') or {}).get(k, [])
        if not clips:
            continue
        ch = [loop(clips, D, sr, rng) for _ in range(1 if k == 'rumble' else 2)]
        ch = [c / (np.sqrt(np.mean(c ** 2)) + 1e-9) * 0.1 * AMB_LEVEL[k] for c in ch]
        out += (np.stack([ch[0], ch[-1]], 1) * (0.7071 if k == 'rumble' else 1.0)).astype(np.float32)
        made.append((k, AMB_KO[k]))
    return out, made


def machine_source(sc, mats):
    """소리 시퀀스의 재료 → (조각, 이름). synth: 합성 선풍기·형광등 · derived: 장면의 기계음(전기 험 등), 없으면 첫 오브제 울림."""
    if get(sc).get('amb_source') == 'synth':
        mk = machine_kind(sc)
        clips = (mats.get('amb') or {}).get(mk, [])
        return (clips[0], AMB_KO[mk]) if clips else (None, None)
    ev = mats.get('event') or {}
    for k in MACHINE_KEYS:
        if ev.get(k):
            from .read import EVENT_NAME
            return max(ev[k], key=len), EVENT_NAME.get(k, k)
    for o in sc.get('objects') or []:
        clips = (mats.get('object') or {}).get(o['idx'], [])
        if clips:
            return max(clips, key=len), '%s 울림' % o['name']
    return None, None


# ── 4 렌더: 먼 라디오 ───────────────────────────────────────────────────
RADIO_WORDS = ('라디오', '노래', '음악', '선율', '멜로디', '방송', '스피커', '흥얼')


def radio(sc, D, sr, rng):
    """장면 안의 음악 — 작은 스피커에서 나오는 듯한 노래. 선율은 꿈 전체의 5음 동기(composition.plan)를 쓴다.
    → (스테레오, 시작 초, 길이, (문장, 위치) 또는 None, 이유)"""
    from .composition import _hz, motif_notes
    m = sc.get('music')
    if not m:
        return None
    sents = sc.get('story_sents') or []
    hit = [(u, s) for u, s in sents if any(w in s for w in RADIO_WORDS)]
    if hit:
        u0, sent = hit[0]
        why = '이야기에 소리 나는 기계·노래가 나오는 문장'
    else:
        cand = [(u, s) for u, s in sents if 0.25 <= u <= 0.65] or sents or [(0.45, None)]
        u0, sent = min(cand, key=lambda x: abs(x[0] - 0.45))
        why = '장면 가운데쯤 — 배경 음악 대신 장면 안 어딘가에서 들리는 노래'
    notes = motif_notes(m, sc['stage'])
    notes = notes + notes[::-1] + notes                            # 짧은 노래 한 소절처럼
    nat = natural(sc)
    beat = nat.get('radio_beat', 0.42)
    rub = nat.get('rubato', 0.0)
    if rub:                                                        # 음마다 조금씩 늘고 줄어든다 (박자기에 맞춘 듯하지 않게)
        notes = [(mt, r * float(np.clip(1 + rub * rng.standard_normal(), 0.8, 1.25))) for mt, r in notes]
    total = sum(r for _, r in notes) * beat + 1.0
    n = int(total * sr)
    y = np.zeros(n)
    t = 0.3
    for mt, r in notes:
        f = _hz(mt + 12 if mt < 60 else mt)
        L = int(r * beat * sr * 0.95)
        tt = np.arange(L) / sr
        vib = 1 + 0.006 * np.sin(2 * np.pi * 5.5 * tt)
        ph = 2 * np.pi * np.cumsum(f * vib) / sr
        tone = np.sin(ph) + 0.35 * np.sin(3 * ph) + 0.18 * np.sin(5 * ph)     # 홀수 배음 — 낡은 오르간·전자음 같은 결
        envl = np.minimum(1, tt / 0.02) * np.exp(-tt / max(0.25, r * beat))
        i0 = int(t * sr)
        y[i0:i0 + L] += (tone * envl)[:len(y[i0:i0 + L])]
        t += r * beat
    root = _hz(m['root_midi'] + m['key_shift'] + 12)
    tt = np.arange(n) / sr
    y += 0.25 * np.sin(2 * np.pi * root * tt) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * (1 / (2 * beat)) * tt)))  # 반주 박
    y = synth.bandpass(y, 350, 3200, sr)                           # 작은 스피커
    y = np.tanh(2.2 * y / (np.max(np.abs(y)) + 1e-9))              # 살짝 찌그러짐
    hiss = 0.03 * synth.bandpass(rng.standard_normal(n), 2000, 6000, sr)
    clicks = (rng.random(n) < 0.0006) * rng.uniform(-0.3, 0.3, n)
    y = synth.lowpass(y + hiss + clicks, 2600, sr) * np.minimum(1, tt / 0.8) * np.minimum(1, (total - tt) / 0.8)
    y = (y / (np.max(np.abs(y)) + 1e-9) * 0.16).astype(np.float32)
    p = float(rng.choice([-0.6, 0.6]))
    a = (p + 1) * math.pi / 4
    st = np.stack([y * math.cos(a), y * math.sin(a)], 1)
    t0 = float(np.clip(u0 * D, 0.05 * D, 0.95 * D - total))
    return st, t0, total, ((sent, u0) if sent else None), why


def flat_arc(A, u, stage):
    """평평한 곡선 — 막의 곡선을 15%만 남기고, 결 장면은 끝 25%에서 천천히 낮춘다."""
    A = 0.9 + 0.15 * (A - float(np.mean(A)))
    if stage == '결':
        A = A * (1 - 0.5 * np.clip((u - 0.75) / 0.25, 0, 1) ** 1.5)
    return A
