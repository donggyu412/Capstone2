"""꿈의 변형 — 효과음을 '그대로' 들려주지 않고 꿈처럼 비튼다 (창발적 장치 4가지).

  ① 이질적 침입   장면 분위기와 맞지 않는 소리가 갑자기 지나간다
                   (공포 장면에 오르골·하프·피리·실로폰·칼림바·자전거 벨·아이 웃음·태엽 장난감… 14종 /
                    밝은 장면에 으르렁·뱃고동·사이렌·천둥·발소리·징·열리는 문·속삭임… 12종)
                   이야기에 '갑자기·순간·스스로·저절로·처음으로' 같은 문장이 있으면 그 자리에, 없으면 정점 둘레에.
                   왼쪽에서 오른쪽으로 지나가며 음높이가 살짝 휜다(도플러) — '지나간다'.
  ② 음색 치환     살아 있는 것의 '몸짓'을 그 장면 재질의 '음색'으로 연주한다
                   (새의 지저귐 × 녹슨 철판 = 기계가 우는 새 / 고양이 울음 × 종이 / 고래 노래 × 형광등 험 …)
                   몸짓은 이야기에 '없는' 생물 16종(새·귀뚜라미·심장·숨·개구리·고양이·날갯짓·부엉이·고래·
                   개·늑대·벌·갈매기·돌고래·매미·뻐꾸기)에서 고르고, 장면마다 돌아가며 다른 생물이 나온다 (새 1순위 없음).
  ③ 변신          한 소리가 몇 초에 걸쳐 다른 오브제의 소리로 바뀐다 (스펙트럼 보간)
                   — 배경 엔진의 '옛 자리 → 새 자리' 모핑을 소리로 옮긴 것
  ④ 데자뷔        장면 앞부분의 소리가 뒤에서 느리게 · 거꾸로 · 멀리서 되돌아온다

근거 (PAPERS.md §8): 음색 전이 — Engel et al. 2020 (DDSP) · Huang et al. 2019 (TimbreTron) /
기대 위반과 놀람 — Huron 2006† / 변형적 창의성 — Boden 2004†.
모두 결정적이다: 같은 악보·같은 시드면 같은 위치에 같은 변형 (무작위로 흐름을 정하지 않는다 — 3팀 원칙).
세기는 막이 정한다(render.STAGE — 전에서 가장 세고, 각성이 높을수록 세게).
"""
import math

import numpy as np
from scipy import signal

from . import synth

SUDDEN = ['갑자기', '순간', '문득', '처음으로', '스스로', '저절로', '저 혼자', '멈춘다', '멈추고', '꺼진다', '사라진다',
          '사라지', '떠오른다', '떠오르']
LIVING = {   # 몸짓 후보 — 이 낱말이 이야기에 있으면 그 생물은 '이질적'이지 않으므로 빼고 고른다
    'bird': [' 새가', ' 새는', ' 새를', ' 새의', ' 새들', '새소리', '새 소리', '까마귀', '지저귀'],   # '냄새·새로' 와 겹치지 않게
    'cricket': ['귀뚜라미', '벌레'],
    'heart': ['심장', '맥박', '고동'],
    'breath': ['숨', '호흡'],
    'frog': ['개구리'],
    'cat': ['고양이', '야옹'],
    'wing': ['날개', '날갯짓', '나방', '박쥐'],
    'owl': ['부엉이', '올빼미'],
    'whale': ['고래'],
    'dog': [' 개가', ' 개는', ' 개의', '강아지', '짖'],          # ' 개' 는 '개구리 · 세 개' 와 겹치지 않게 앞에 빈칸
    'wolf': ['늑대'],
    'bee': ['꿀벌', ' 벌이', ' 벌떼', '윙윙'],                   # '벌어진다' 와 겹치지 않게
    'seagull': ['갈매기'],
    'dolphin': ['돌고래'],
    'cicada': ['매미'],
    'cuckoo': ['뻐꾸기'],
}
# 이질적 침입 후보 — 어두운 장면에는 밝은 소리, 밝은 장면에는 어두운 소리 (10-08: 새에 치우치지 않게 늘림)
INTRUDE_BRIGHT = ['musicbox', 'bird', 'chime', 'whistle', 'harp', 'hum', 'bubble', 'cricket',
                  'flute', 'xylophone', 'kalimba', 'bikebell', 'laugh', 'toy']                    # 14종
INTRUDE_DARK = ['growl', 'scrape', 'heart', 'horn', 'knock', 'owl',
                'siren', 'thunder', 'footsteps', 'gong', 'door', 'whisper']                      # 12종
INTRUDE_WORDS = {   # 이야기에 이미 있는 소리는 '이질적'이 아니므로 침입에서 뺀다
    'musicbox': ['오르골'], 'chime': ['풍경'], 'whistle': ['휘파람'], 'harp': ['하프'], 'hum': ['허밍', '흥얼'],
    'flute': ['피리', '플루트'], 'xylophone': ['실로폰'], 'kalimba': ['칼림바'], 'bikebell': ['자전거', '따르릉'],
    'laugh': ['웃음', '웃는', '깔깔'], 'toy': ['장난감', '태엽'], 'horn': ['뱃고동', '고동'], 'knock': ['노크', '두드린', '두드리', '두드려'],
    'siren': ['사이렌'], 'thunder': ['천둥', '번개'], 'footsteps': ['발소리', '발자국', '걸음'], 'gong': [' 징', '징 소리'],
    'door': [' 문이', ' 문을', '문틈', '문고리'], 'whisper': ['속삭'], 'scrape': ['긁'], 'growl': ['으르렁'],
    'bubble': ['거품', '기포']}
GESTURE_KO = {'bird': '새의 지저귐', 'cricket': '귀뚜라미 울음', 'heart': '심장 박동', 'breath': '숨',
              'musicbox': '오르골', 'chime': '풍경 소리', 'whistle': '먼 휘파람', 'growl': '낮은 으르렁거림',
              'scrape': '쇠 긁힘', 'harp': '하프 아르페지오', 'hum': '허밍', 'bubble': '거품 소리', 'horn': '먼 뱃고동',
              'knock': '느린 노크', 'frog': '개구리 울음', 'cat': '고양이 울음', 'wing': '날갯짓', 'owl': '부엉이 울음',
              'whale': '고래 노래', 'flute': '먼 피리 선율', 'xylophone': '실로폰 동요', 'kalimba': '칼림바',
              'bikebell': '자전거 벨', 'laugh': '먼 아이 웃음', 'toy': '태엽 장난감', 'siren': '먼 사이렌',
              'thunder': '먼 천둥', 'footsteps': '보이지 않는 발소리', 'gong': '낮은 징', 'door': '열리는 문',
              'whisper': '속삭임', 'dog': '먼 개 짖음', 'wolf': '늑대 울음', 'bee': '벌 날갯짓', 'seagull': '갈매기 울음',
              'dolphin': '돌고래 휘파람', 'cicada': '매미 울음', 'cuckoo': '뻐꾸기 울음'}
TIMBRE_KO = {'metal': '녹슨 철판', 'electric': '형광등 전기 험', 'paper': '종이', 'glass': '얼음·유리',
             'liquid': '액체', 'wood': '나무', 'stone': '돌·타일', 'object': '오브제'}


# ── 몸짓: (주파수 곡선 f(t), 세기 곡선 a(t)) ─────────────────────────────────
def _blank(dur, sr):
    n = int(dur * sr)
    return np.zeros(n), np.zeros(n), n


def g_bird(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    t = 0.1
    while t < dur - 0.3:
        for _ in range(int(rng.integers(3, 7))):                      # 지저귐 한 무리
            L = int(sr * rng.uniform(0.05, 0.13))
            i = int(t * sr)
            if i + L >= n:
                break
            f0, f1 = rng.uniform(2200, 3600), rng.uniform(2600, 4600)
            if rng.random() < 0.5:
                f0, f1 = f1, f0
            f[i:i + L] = np.linspace(f0, f1, L)
            a[i:i + L] = np.sin(np.linspace(0, np.pi, L)) ** 0.7
            t += L / sr + rng.uniform(0.03, 0.09)
        t += rng.uniform(0.25, 0.55)
    return f, a


def g_cricket(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    f[:] = rng.uniform(3900, 4700)
    t = 0.05
    while t < dur - 0.2:
        for k in range(4):
            i, L = int((t + k * 0.033) * sr), int(0.016 * sr)
            a[i:i + L] = np.hanning(L)
        t += rng.uniform(0.3, 0.42)
    return f, a


def g_heart(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    period = 60 / rng.uniform(58, 72)
    t = 0.05
    while t < dur - 0.4:
        for off, L, g in ((0.0, 0.11, 1.0), (0.27, 0.09, 0.7)):      # 쿵-쿵 (lub-dub)
            i, m = int((t + off) * sr), int(L * sr)
            if i + m < n:
                f[i:i + m] = np.linspace(62, 38, m)
                a[i:i + m] = g * np.exp(-np.linspace(0, 5, m))
        t += period
    return f, a


def g_breath(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    cyc = rng.uniform(2.2, 3.2)
    ph = (t % cyc) / cyc
    a[:] = np.sin(np.pi * np.clip(ph / 0.85, 0, 1)) ** 2
    f[:] = 450 + 350 * ph
    return f, a


def g_musicbox(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    scale = [0, 2, 4, 7, 9, 12, 14, 16]                                # 장조 5음음계 — 공포 장면과 정반대의 밝음
    base = 1046.5
    t, k = 0.05, int(rng.integers(0, 4))
    while t < dur - 0.3:
        L = int(sr * rng.uniform(0.2, 0.32))
        i = int(t * sr)
        k = int(np.clip(k + rng.integers(-2, 3), 0, len(scale) - 1))
        f[i:i + L] = base * 2 ** (scale[k] / 12)
        a[i:i + L] = np.exp(-np.linspace(0, 4, L))[:len(a[i:i + L])]
        t += L / sr
    return f, a


def g_chime(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    t = 0.05
    while t < dur - 0.4:
        L = int(sr * rng.uniform(0.35, 0.7))
        i = int(t * sr)
        f[i:i + L] = rng.uniform(1500, 3800)
        a[i:i + L] = np.exp(-np.linspace(0, 2.5, L))[:len(a[i:i + L])] * rng.uniform(0.7, 1)
        t += L / sr * rng.uniform(0.3, 0.6)
    return f, a


def g_whistle(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = np.linspace(rng.uniform(1600, 2000), rng.uniform(1200, 1500), n) * (1 + 0.008 * np.sin(2 * np.pi * 5.5 * t))
    a[:] = np.sin(np.pi * t / dur) ** 1.5
    return f, a


def g_growl(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = 70 + 15 * np.sin(2 * np.pi * 0.7 * t)
    a[:] = np.sin(np.pi * t / dur) * (0.7 + 0.3 * np.sin(2 * np.pi * 11 * t))
    return f, a


def g_scrape(dur, sr, rng):
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = np.linspace(rng.uniform(300, 500), rng.uniform(900, 1400), n)
    a[:] = np.sin(np.pi * t / dur) * (0.6 + 0.4 * (rng.random(n) > 0.3))
    return f, a


def g_harp(dur, sr, rng):
    """하프 아르페지오 — 5음음계를 오르내리며 튕긴다."""
    f, a, n = _blank(dur, sr)
    scale = [0, 2, 4, 7, 9, 12, 14, 16, 19]
    base = rng.choice([392.0, 440.0, 523.3])
    t, k, step = 0.05, 0, 1
    while t < dur - 0.3:
        L = int(sr * 0.16)
        i = int(t * sr)
        f[i:i + L] = base * 2 ** (scale[k] / 12)
        a[i:i + L] = np.exp(-np.linspace(0, 5, L))[:len(a[i:i + L])]
        k += step
        if k in (0, len(scale) - 1):
            step = -step
        t += 0.13
    return f, a


def g_hum(dur, sr, rng):
    """허밍 — 느린 선율을 떨림과 함께 흥얼거린다."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    notes = [220 * 2 ** (x / 12) for x in rng.choice([0, 2, 3, 5, 7, 9], size=4)]
    seg = n // 4
    for j, fr in enumerate(notes):
        f[j * seg:(j + 1) * seg] = fr
    f[:] = signal.savgol_filter(f, min(n - 1 - (n % 2 == 0), int(sr * 0.15) | 1), 2) * (1 + 0.01 * np.sin(2 * np.pi * 5 * t))
    a[:] = np.sin(np.pi * t / dur) ** 1.2
    return f, a


def g_bubble(dur, sr, rng):
    """거품 소리 — 짧게 위로 휘는 '뽁' 들."""
    f, a, n = _blank(dur, sr)
    t = 0.05
    while t < dur - 0.2:
        L = int(sr * rng.uniform(0.04, 0.09))
        i = int(t * sr)
        f0 = rng.uniform(400, 900)
        f[i:i + L] = np.linspace(f0, f0 * 2.2, L)
        a[i:i + L] = np.exp(-np.linspace(0, 4, L))[:len(a[i:i + L])]
        t += L / sr + rng.uniform(0.08, 0.35)
    return f, a


def g_horn(dur, sr, rng):
    """먼 뱃고동 — 낮고 긴 두 음."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    h = n // 2
    f[:h], f[h:] = rng.uniform(90, 110), rng.uniform(75, 90)
    a[:] = np.concatenate([np.sin(np.pi * np.linspace(0, 1, h)) ** 0.6, np.sin(np.pi * np.linspace(0, 1, n - h)) ** 0.6])
    return f, a


def g_knock(dur, sr, rng):
    """느린 노크 — 똑, 똑, 똑."""
    f, a, n = _blank(dur, sr)
    gap = rng.uniform(0.45, 0.7)
    t = 0.1
    while t < dur - 0.2:
        L = int(sr * 0.09)
        i = int(t * sr)
        f[i:i + L] = rng.uniform(160, 220)
        a[i:i + L] = np.exp(-np.linspace(0, 6, L))[:len(a[i:i + L])]
        t += gap
    return f, a


def g_frog(dur, sr, rng):
    """개구리 울음 — 빠르게 떨리는 낮은 '개굴' 다발."""
    f, a, n = _blank(dur, sr)
    t = 0.05
    while t < dur - 0.4:
        L = int(sr * rng.uniform(0.25, 0.4))
        i = int(t * sr)
        tt = np.arange(L) / sr
        f[i:i + L] = rng.uniform(180, 260) * (1 + 0.1 * tt / tt[-1])
        a[i:i + L] = (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 26 * tt))) * np.hanning(L)
        t += L / sr + rng.uniform(0.3, 0.6)
    return f, a


def g_cat(dur, sr, rng):
    """고양이 울음 — 올라갔다 내려오는 '야옹'."""
    f, a, n = _blank(dur, sr)
    t = 0.1
    while t < dur - 0.9:
        L = int(sr * rng.uniform(0.6, 0.9))
        i = int(t * sr)
        x = np.linspace(0, 1, L)
        f0 = rng.uniform(420, 520)
        f[i:i + L] = f0 * (1 + 0.7 * np.sin(np.pi * x ** 0.7))
        a[i:i + L] = np.sin(np.pi * x) ** 0.8
        t += L / sr + rng.uniform(0.4, 0.9)
    return f, a


def g_wing(dur, sr, rng):
    """날갯짓 — 초당 8~12번 퍼덕임, 점점 멀어진다."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    rate = rng.uniform(8, 12)
    f[:] = 300 + 150 * np.sin(2 * np.pi * rate * t)
    a[:] = np.maximum(0, np.sin(2 * np.pi * rate * t)) ** 3 * np.exp(-t / (dur * 0.7))
    return f, a


def g_owl(dur, sr, rng):
    """부엉이 울음 — '부-엉' 두 음 한 쌍."""
    f, a, n = _blank(dur, sr)
    t = 0.1
    while t < dur - 0.9:
        for fr, L in ((rng.uniform(360, 400), 0.32), (rng.uniform(300, 330), 0.45)):
            i, m = int(t * sr), int(L * sr)
            if i + m < n:
                f[i:i + m] = fr
                a[i:i + m] = np.sin(np.pi * np.linspace(0, 1, m)) ** 0.7
            t += L + 0.08
        t += rng.uniform(0.6, 1.0)
    return f, a


def g_whale(dur, sr, rng):
    """고래 노래 — 느리게 오르내리는 긴 미끄러짐."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f0, f1 = rng.uniform(140, 200), rng.uniform(350, 480)
    f[:] = f0 + (f1 - f0) * np.sin(np.pi * t / dur) ** 2
    a[:] = np.sin(np.pi * t / dur) ** 0.8
    return f, a


# ── 10-08 2차 추가: 침입 소리 12종 · 생물 7종 ──────────────────────────────
def _notes(dur, sr, rng, pitches, L_rng, gap_rng, shape='decay', k=5.0):
    """음 목록을 차례로 — 선율류 공용 (shape: decay = 친 소리, swell = 부는 소리)."""
    f, a, n = _blank(dur, sr)
    t = 0.08
    j = 0
    while t < dur - 0.15:
        L = int(sr * rng.uniform(*L_rng))
        i = int(t * sr)
        if i + L >= n:
            break
        f[i:i + L] = pitches[j % len(pitches)]
        x = np.linspace(0, 1, L)
        a[i:i + L] = np.exp(-k * x) if shape == 'decay' else np.sin(np.pi * x) ** 0.5
        t += L / sr + rng.uniform(*gap_rng)
        j += 1
    return f, a


def _scale(rng, base, steps, n):
    return [base * 2 ** (steps[int(i)] / 12) for i in rng.integers(0, len(steps), n)]


def g_flute(dur, sr, rng):
    """먼 피리 선율 — 오음 음계를 숨결처럼 이어 분다 (살짝 떨림)."""
    f, a = _notes(dur, sr, rng, _scale(rng, rng.uniform(520, 620), [0, 2, 4, 7, 9, 12], 12), (0.28, 0.55), (0.0, 0.05), 'swell')
    t = np.arange(len(f)) / sr
    return f * (1 + 0.008 * np.sin(2 * np.pi * 5.2 * t)), a


def g_xylophone(dur, sr, rng):
    """실로폰 동요 — 짧게 똑똑 끊기는 장조 선율."""
    return _notes(dur, sr, rng, _scale(rng, rng.uniform(700, 820), [0, 2, 4, 5, 7, 9, 12], 16), (0.12, 0.18), (0.05, 0.12), 'decay', 7)


def g_kalimba(dur, sr, rng):
    """칼림바 — 엄지 피아노의 둥근 음, 천천히 퉁긴다."""
    return _notes(dur, sr, rng, _scale(rng, rng.uniform(380, 460), [0, 3, 5, 7, 10, 12], 10), (0.4, 0.6), (0.05, 0.2), 'decay', 4)


def g_bikebell(dur, sr, rng):
    """자전거 벨 — '따르릉' 두 번."""
    f, a, n = _blank(dur, sr)
    f0 = rng.uniform(2300, 2700)
    for t0 in (0.15, min(dur - 0.9, 0.15 + rng.uniform(1.0, 1.6))):
        for r in range(6):                                                  # 따르르릉 — 빠른 연타
            i, L = int((t0 + r * 0.045) * sr), int(0.6 * sr)
            if i + L < n:
                f[i:i + L] = f0
                a[i:i + L] = np.maximum(a[i:i + L], np.exp(-np.linspace(0, 6, L)))
    return f, a


def g_laugh(dur, sr, rng):
    """먼 아이 웃음 — '하하하' 짧은 음절이 내려오며 이어진다."""
    f, a, n = _blank(dur, sr)
    t = 0.1
    while t < dur - 0.8:
        p = rng.uniform(380, 460)
        for k in range(int(rng.integers(4, 7))):
            L, i = int(sr * 0.09), int(t * sr)
            if i + L >= n:
                break
            f[i:i + L] = p * (0.97 ** k) * np.linspace(1.05, 0.95, L)
            a[i:i + L] = np.sin(np.pi * np.linspace(0, 1, L)) ** 0.6
            t += 0.15
        t += rng.uniform(0.6, 1.1)
    return f, a


def g_toy(dur, sr, rng):
    """태엽 장난감 — 빠르게 오르내리는 '삐요삐요', 끝으로 갈수록 느려진다(태엽이 풀림)."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    rate = 7 * np.exp(-t / dur)                                             # 태엽이 풀리며 느려짐
    ph = np.cumsum(rate) / sr
    f[:] = rng.uniform(900, 1100) * (1 + 0.35 * np.sign(np.sin(2 * np.pi * ph)))
    a[:] = 0.8 * (1 - 0.6 * t / dur)
    return f, a


def g_siren(dur, sr, rng):
    """먼 사이렌 — 느리게 오르내리는 울음."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = rng.uniform(500, 600) * (1 + 0.45 * (0.5 + 0.5 * np.sin(2 * np.pi * t / rng.uniform(1.6, 2.2))))
    a[:] = np.sin(np.pi * t / dur) ** 0.7
    return f, a


def g_thunder(dur, sr, rng):
    """먼 천둥 — 낮은 잡음이 우르릉 굴러간다."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = rng.uniform(70, 110)
    env = np.exp(-t / (dur * 0.45)) * (1 - np.exp(-t / 0.08))
    a[:] = env * (0.6 + 0.4 * np.abs(np.sin(2 * np.pi * rng.uniform(2.5, 4) * t + rng.uniform(0, 6))))
    return f, a


def g_footsteps(dur, sr, rng):
    """보이지 않는 발소리 — 일정한 걸음이 지나간다."""
    f, a, n = _blank(dur, sr)
    gap = rng.uniform(0.5, 0.65)
    t = 0.1
    while t < dur - 0.2:
        L, i = int(sr * 0.12), int(t * sr)
        f[i:i + L] = rng.uniform(110, 150)
        a[i:i + L] = np.exp(-np.linspace(0, 5, L))[:len(a[i:i + L])]
        t += gap * rng.uniform(0.95, 1.05)
    return f, a


def g_gong(dur, sr, rng):
    """낮은 징 — 한 번 치고 길게 울린다 (음이 살짝 내려앉음)."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = rng.uniform(95, 125) * (1 - 0.03 * t / dur)
    a[:] = np.exp(-t / (dur * 0.5)) * (1 - np.exp(-t / 0.01))
    return f, a


def g_door(dur, sr, rng):
    """천천히 열리는 문 — 삐이걱, 음높이가 끊기듯 미끄러진다."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = rng.uniform(250, 320) + rng.uniform(150, 300) * np.sin(np.pi * t / dur) ** 2
    a[:] = np.sin(np.pi * t / dur) ** 0.6 * (0.6 + 0.4 * (np.sin(2 * np.pi * 31 * t) > 0))   # 마찰의 끊김
    return f, a


def g_whisper(dur, sr, rng):
    """알아들을 수 없는 속삭임 — '스'와 '흐'가 섞인 음절."""
    f, a, n = _blank(dur, sr)
    t = 0.1
    while t < dur - 0.3:
        L, i = int(sr * rng.uniform(0.12, 0.3)), int(t * sr)
        if i + L >= n:
            break
        f[i:i + L] = rng.choice([1800, 3200, 5200])                         # 흐 · 쉬 · 스
        a[i:i + L] = np.sin(np.pi * np.linspace(0, 1, L)) ** 1.2
        t += L / sr + rng.uniform(0.03, 0.2)
    return f, a


def g_dog(dur, sr, rng):
    """먼 개 짖음 — '컹, 컹' 짧고 굵게."""
    f, a, n = _blank(dur, sr)
    t = 0.1
    while t < dur - 0.4:
        for _ in range(int(rng.integers(1, 3))):
            L, i = int(sr * 0.16), int(t * sr)
            if i + L >= n:
                break
            f[i:i + L] = rng.uniform(380, 460) * np.linspace(1.15, 0.8, L)
            a[i:i + L] = np.exp(-np.linspace(0, 3.5, L)) * (1 - np.exp(-np.linspace(0, 40, L)))
            t += 0.25
        t += rng.uniform(0.6, 1.2)
    return f, a


def g_wolf(dur, sr, rng):
    """늑대 울부짖음 — 올라가서 길게 끌다 내려온다."""
    f, a, n = _blank(dur, sr)
    x = np.linspace(0, 1, n)
    f0 = rng.uniform(300, 360)
    f[:] = f0 * (1 + 0.8 * np.minimum(1, x * 4) - 0.5 * np.maximum(0, x - 0.7) / 0.3)
    a[:] = np.sin(np.pi * x) ** 0.5
    return f, a


def g_bee(dur, sr, rng):
    """벌 날갯짓 — 윙윙, 가까워졌다 멀어지며 음높이가 흔들린다."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = rng.uniform(210, 250) * (1 + 0.06 * np.sin(2 * np.pi * rng.uniform(0.7, 1.4) * t))
    a[:] = np.sin(np.pi * t / dur) ** 0.8
    return f, a


def g_seagull(dur, sr, rng):
    """갈매기 — 높게 꺾여 내려오는 '끼욱 끼욱'."""
    f, a, n = _blank(dur, sr)
    t = 0.1
    while t < dur - 0.5:
        L, i = int(sr * rng.uniform(0.25, 0.35)), int(t * sr)
        x = np.linspace(0, 1, L)
        f[i:i + L] = rng.uniform(1300, 1600) * (1 + 0.4 * x - 0.9 * x ** 2)
        a[i:i + L] = np.sin(np.pi * x) ** 0.5
        t += L / sr + rng.uniform(0.15, 0.5)
    return f, a


def g_dolphin(dur, sr, rng):
    """돌고래 휘파람 — 높고 빠른 미끄러짐과 딸깍."""
    f, a, n = _blank(dur, sr)
    t = 0.05
    while t < dur - 0.4:
        L, i = int(sr * rng.uniform(0.3, 0.5)), int(t * sr)
        x = np.linspace(0, 1, L)
        f[i:i + L] = rng.uniform(4000, 6000) + rng.uniform(-2000, 2000) * np.sin(np.pi * x * rng.uniform(1, 2.5))
        a[i:i + L] = np.sin(np.pi * x) ** 0.7
        t += L / sr + rng.uniform(0.1, 0.4)
    return f, a


def g_cicada(dur, sr, rng):
    """매미 — 높은 음이 빠르게 떨리며 차올랐다 잦아든다."""
    f, a, n = _blank(dur, sr)
    t = np.arange(n) / sr
    f[:] = rng.uniform(5000, 6200)
    a[:] = (0.55 + 0.45 * np.sign(np.sin(2 * np.pi * 120 * t))) * np.sin(np.pi * t / dur) ** 0.6
    return f, a


def g_cuckoo(dur, sr, rng):
    """뻐꾸기 — '뻐-꾹' 장3도 아래로 두 음."""
    f, a, n = _blank(dur, sr)
    f0 = rng.uniform(640, 720)
    t = 0.1
    while t < dur - 0.7:
        for fr in (f0, f0 / 2 ** (4 / 12)):
            L, i = int(sr * 0.22), int(t * sr)
            if i + L < n:
                f[i:i + L] = fr
                a[i:i + L] = np.sin(np.pi * np.linspace(0, 1, L)) ** 0.5
            t += 0.28
        t += rng.uniform(0.5, 0.9)
    return f, a


GESTURES = {'bird': g_bird, 'cricket': g_cricket, 'heart': g_heart, 'breath': g_breath, 'musicbox': g_musicbox,
            'chime': g_chime, 'whistle': g_whistle, 'growl': g_growl, 'scrape': g_scrape,
            'harp': g_harp, 'hum': g_hum, 'bubble': g_bubble, 'horn': g_horn, 'knock': g_knock, 'frog': g_frog,
            'cat': g_cat, 'wing': g_wing, 'owl': g_owl, 'whale': g_whale,
            'flute': g_flute, 'xylophone': g_xylophone, 'kalimba': g_kalimba, 'bikebell': g_bikebell, 'laugh': g_laugh,
            'toy': g_toy, 'siren': g_siren, 'thunder': g_thunder, 'footsteps': g_footsteps, 'gong': g_gong,
            'door': g_door, 'whisper': g_whisper, 'dog': g_dog, 'wolf': g_wolf, 'bee': g_bee, 'seagull': g_seagull,
            'dolphin': g_dolphin, 'cicada': g_cicada, 'cuckoo': g_cuckoo}
NATURAL_TIMBRE = {'bird': 'sine', 'cricket': 'sine', 'heart': 'sine', 'breath': 'noise', 'musicbox': 'bell',
                  'chime': 'bell', 'whistle': 'sine', 'growl': 'saw', 'scrape': 'noise', 'harp': 'bell', 'hum': 'sine',
                  'bubble': 'sine', 'horn': 'saw', 'knock': 'wood', 'frog': 'saw', 'cat': 'sine', 'wing': 'noise',
                  'owl': 'sine', 'whale': 'sine',
                  'flute': 'sine', 'xylophone': 'wood', 'kalimba': 'bell', 'bikebell': 'bell', 'laugh': 'sine',
                  'toy': 'sine', 'siren': 'sine', 'thunder': 'noise', 'footsteps': 'wood', 'gong': 'bell',
                  'door': 'saw', 'whisper': 'noise', 'dog': 'saw', 'wolf': 'sine', 'bee': 'saw', 'seagull': 'sine',
                  'dolphin': 'sine', 'cicada': 'sine', 'cuckoo': 'sine'}


# ── 음색: 몸짓을 어떤 재질로 연주하나 ────────────────────────────────────────
def _partials(f, a, sr, ratios, weights, rng):
    out = np.zeros(len(f))
    for r, w in zip(ratios, weights):
        fr = np.minimum(f * r, sr / 2 - 200)
        out += w * np.sin(2 * np.pi * np.cumsum(fr) / sr + rng.uniform(0, 6.28))
    return out * a


def _noise_follow(f, a, sr, rng, width=0.25):
    """잡음을 매 순간 f 둘레로만 통과 — 종이·숨 같은 결로 몸짓을 그린다 (STFT 마스크)."""
    nper = 1024
    x = rng.standard_normal(len(f))
    fr, tt, Z = signal.stft(x, sr, nperseg=nper)
    idx = np.clip((tt * sr).astype(int), 0, len(f) - 1)
    fc = np.maximum(f[idx], 60)[None, :]
    mask = np.exp(-0.5 * ((fr[:, None] - fc) / (fc * width)) ** 2)
    _, y = signal.istft(Z * mask, sr, nperseg=nper)
    y = y[:len(f)]
    if len(y) < len(f):
        y = np.pad(y, (0, len(f) - len(y)))
    return y * a


def timbre(kind, f, a, sr, rng, obj_feat=None):
    if kind == 'sine':
        return _partials(f, a, sr, [1, 2, 3], [1, 0.12, 0.04], rng)
    if kind == 'bell':
        return _partials(f, a, sr, [1, 2.0, 2.76, 5.4], [1, 0.35, 0.25, 0.1], rng)
    if kind == 'saw':
        return _partials(f, a, sr, range(1, 12), [1 / k for k in range(1, 12)], rng)
    if kind == 'noise':
        return _noise_follow(f, a, sr, rng, 0.35)
    if kind == 'metal':                                                  # 비조화 금속 막대 모드 (1 : 2.76 : 5.40 : 8.93)
        y = _partials(f * 0.5, a, sr, [1, 2.76, 5.40, 8.93], [1, 0.6, 0.35, 0.2], rng)
        return y + 0.3 * _noise_follow(f * 1.3, a, sr, rng, 0.08)
    if kind == 'electric':                                               # 전기 험: 톱니파 + 60Hz 떨림 + 고역 지글거림
        t = np.arange(len(f)) / sr
        y = _partials(f * 0.5, a, sr, range(1, 9), [1 / k for k in range(1, 9)], rng)
        y *= 0.55 + 0.45 * np.sign(np.sin(2 * np.pi * 60 * t))
        return y + 0.25 * synth.bandpass(rng.standard_normal(len(f)), 2500, 6000, sr) * a
    if kind == 'paper':
        return _noise_follow(f, a, sr, rng, 0.18) * (0.6 + 0.4 * (rng.random(len(f)) > 0.5))
    if kind == 'glass':
        return _partials(f * 1.4, a, sr, [1, 2.32, 4.25, 6.63], [1, 0.5, 0.3, 0.15], rng)
    if kind == 'liquid':
        t = np.arange(len(f)) / sr
        return _partials(f * (1 + 0.15 * ((t * 23) % 1)), a, sr, [1], [1], rng)   # 몸짓 위에 기포의 위로 휘는 결
    if kind == 'wood':                                                   # 나무 막대: 짧고 둥근 배음 (1 : 2.57 : 4.2) + 마른 결
        return _partials(f * 0.7, a, sr, [1, 2.57, 4.2], [1, 0.4, 0.15], rng) + 0.15 * _noise_follow(f, a, sr, rng, 0.3)
    if kind == 'stone':                                                  # 돌·타일: 높고 짧은 '딱'의 비조화 배음
        t = np.arange(len(f)) / sr
        taps = np.exp(-((t * 14) % 1) * 9)                               # 초당 14번 '딱딱' — 몸짓을 잘게 두드려 그린다
        return _partials(f * 1.2, a, sr, [1, 1.63, 2.9, 4.4], [1, 0.7, 0.5, 0.3], rng) * taps
    if kind == 'object' and obj_feat:
        f0, ratios, decays, amps = synth.modal_params(obj_feat)
        return _partials(f, a, sr, ratios[:6], amps[:6], rng)
    return _partials(f, a, sr, [1], [1], rng)


# ── 장면 → 변형 계획 ─────────────────────────────────────────────────────
MAT_EVENT = {'metal': 'metal', 'electric': 'electric', 'paper': 'rustle', 'glass': 'ice', 'liquid': 'liquid',
             'wood': 'creak', 'stone': 'crack'}
MAT_WORDS = {'metal': ('철판', '철제', '쇠', '녹슨', '녹이', '금속', '쇳'), 'electric': ('형광등', '전구', '전등', '불빛'),
             'paper': ('종이', '서류', '책장', '페이지'), 'glass': ('얼음', '유리', '서리', '냉기'),
             'liquid': ('웅덩이', '냉동액', '액체')}


def scene_materials(sc):
    """장면의 재질 순위 — 음색 치환에 쓸 '그 장면의 몸'.
    점수 = 이야기 글 속 재질 낱말 수 + 배경·오브제 이름에 있으면 2점. 기계의 몸(금속·전기)은 1.5배 — '기계로 우는 새'.
    10-08: 그림 인식이 있으면 '눈에 보이는 재질'도 더한다 — 배경 재질 확률 ×3 · 오브제 재질 ×2 · 그림 속 형광등 등 소리원 +2."""
    story = ' '.join(st for _, st in (sc.get('story_sents') or []))
    words = ' '.join((sc.get('backgrounds') or []) + [o['name'] for o in sc.get('objects', [])])
    score = {}
    for m, ws in MAT_WORDS.items():
        v = sum(story.count(w) for w in ws) + 2 * sum(w in words for w in ws)
        if v:
            score[m] = v
    for k, _, p in (sc.get('vision_mats') or [])[:3]:
        if k in TIMBRE_KO and k != 'object':
            score[k] = score.get(k, 0) + 3 * p
    for o in sc.get('objects', []):
        k = o['features'].get('material')
        if k in TIMBRE_KO and k != 'object':
            score[k] = score.get(k, 0) + 2 * o['features'].get('material_p', 0)
    for x in sc.get('seen') or []:
        if x['event'] == 'electric':
            score['electric'] = score.get('electric', 0) + 2
    score = {m: v * (1.5 if m in ('metal', 'electric') else 1.0) for m, v in score.items() if v > 0.3}
    order = sorted(score, key=lambda m: -score[m])[:3]
    k = (int(sc.get('num', 1)) - 1) % max(1, len(order))           # 장면마다 상위 재질을 돌아가며 — 4장면이 같은 음색이 되지 않게
    order = order[k:] + order[:k]
    if sc.get('objects'):
        order.insert(min(1, len(order)), 'object')     # 두 번째 치환은 그 장면 오브제의 실루엣 음색으로
    return order or ['metal']


def josa(word, a, b):
    """받침에 따라 조사 고르기 — '휘파람이' / '오르골이' / '새의 지저귐이' / '숨이' ..."""
    ch = word.rstrip()[-1:] or ' '
    code = ord(ch) - 0xAC00
    return word + (a if 0 <= code < 11172 and code % 28 else b)


def _pan_sweep(y, p0, p1):
    th = (np.linspace(p0, p1, len(y)) + 1) * math.pi / 4
    return np.stack([y * np.cos(th), y * np.sin(th)], axis=1)


def _stretch_to(clips, W, sr, rng):
    """재료 조각들을 W 초짜리 흐름으로 (알갱이로 이어 붙임)."""
    n = int(W * sr)
    out = np.zeros(n)
    t = 0
    k = 0
    while t < n and clips:
        c = clips[k % len(clips)]
        L = min(len(c), n - t)
        out[t:t + L] += c[:L] * np.hanning(L) if L > 64 else 0
        t += max(64, int(L * 0.6))
        k += 1
    return out


def morph(A, B, sr):
    """A 의 스펙트럼이 B 의 스펙트럼으로 기하 보간되며 바뀐다 (로그 크기 보간 · 위상은 섞음)."""
    nper = 2048
    _, _, ZA = signal.stft(A, sr, nperseg=nper)
    _, _, ZB = signal.stft(B, sr, nperseg=nper)
    m = min(ZA.shape[1], ZB.shape[1])
    ZA, ZB = ZA[:, :m], ZB[:, :m]
    x = np.linspace(0, 1, m)
    al = (x * x * (3 - 2 * x))[None, :]
    mag = np.exp((1 - al) * np.log(np.abs(ZA) + 1e-7) + al * np.log(np.abs(ZB) + 1e-7))
    ph = np.angle((1 - al) * ZA + al * ZB)
    _, y = signal.istft(mag * np.exp(1j * ph), sr, nperseg=nper)
    return y[:len(A)]


def _norm(y, peak):
    m = np.max(np.abs(y)) + 1e-9
    return (y / m * peak).astype(np.float32)


def apply(sc, P, mats, D, sr, rng, dry, add, note):
    """장면에 꿈의 변형을 얹는다. add(out, y, start) · note(t, dur, kind, name, reason, sentence) 는 render 가 넘긴다."""
    d = float(P.get('dream', 0.5))
    emo = sc['emotion']
    sents = sc.get('story_sents') or []
    story = ' ' + ' '.join(s for _, s in sents)
    dark = emo['valence'] <= 0
    sudden = [(u, s) for u, s in sents if any(w in s for w in SUDDEN)]

    # 놓을 자리 — '갑자기' 류 문장 먼저, 모자라면 정점·3등분 자리
    slots = [(u, s) for u, s in sudden]
    for u in (P.get('arc_peak', 0.5), 0.3, 0.7, 0.5):
        if all(abs(u - v) > 0.12 for v, _ in slots):
            slots.append((u, None))

    in_story = {g for g, ws in list(LIVING.items()) + list(INTRUDE_WORDS.items())
                if any(w in story for w in ws)}                         # 이야기에 있는 소리는 '이질적'이 아니다
    num = int(sc.get('num', 1))

    def rotation(cands, per_scene, tag, allowed):
        """전체 후보를 꿈 전체에서 한 번 섞고, 장면마다 per_scene 칸씩 밀린 자리부터 꺼낸 뒤 쓸 수 없는 것을 뺀다.
        섞는 목록이 장면마다 같아서(걸러내기는 나중) 장면끼리 겹치지 않고 골고루 돈다 (10-08)."""
        order = sorted(cands)
        order = [order[i] for i in synth.rng_for('dream-gestures', tag).permutation(len(order))]
        k = ((num - 1) * per_scene) % max(1, len(order))
        order = order[k:] + order[:k]
        return [g for g in order if g in allowed] or order

    # ① 이질적 침입
    base = INTRUDE_BRIGHT if dark else INTRUDE_DARK
    palette = rotation(base, 3, 'bright' if dark else 'dark', {g for g in base if g not in in_story})
    n_in = 1 + int(d > 0.45) + int(d > 0.8)
    lo, hi = 0.04 * D, 0.96 * D                                          # 장면 경계(겹쳐 섞는 구간)는 피한다
    for k in range(n_in):
        u0, s = slots[k % len(slots)]
        g = palette[k % len(palette)]
        dur = min(float(rng.uniform(2.5, 4.5)), 0.6 * D)
        f, a = GESTURES[g](dur, sr, rng)
        x = np.linspace(0, 1, len(f))
        f = f * (1 + 0.035 * (0.5 - x))                                   # 다가오다 멀어지는 도플러
        y = timbre(NATURAL_TIMBRE[g], f, a, sr, rng) * np.sin(np.pi * x) ** 0.8
        y = synth.lowpass(y, 7000, sr, 1)
        lr = (-0.9, 0.9) if rng.random() < 0.5 else (0.9, -0.9)
        t0 = float(np.clip(u0 * D - dur / 2, min(lo, D - dur), max(0.0, hi - dur)))
        add(dry, _pan_sweep(_norm(y, 0.55 * (0.6 + 0.6 * d)), *lr), int(t0 * sr))
        note(t0, dur, '이질적 침입', '%s %s 지나감' % (josa(GESTURE_KO[g], '이', '가'), '왼쪽→오른쪽' if lr[0] < 0 else '오른쪽→왼쪽'),
             '장면 감정(%s)과 반대되는 %s 소리 — 꿈의 부조화' % (emo['label'], '밝은' if dark else '어두운'),
             (s, u0) if s else None)

    # ② 음색 치환 — 이야기에 없는 생물의 몸짓 × 장면 재질의 음색
    mats_rank = scene_materials(sc)
    n_sub = 1 + int(d > 0.6)
    used = {palette[k % len(palette)] for k in range(n_in)}               # 침입에 쓴 생물은 치환에서 빼서 겹치지 않게
    foreign = rotation(list(LIVING), 2, 'living', {g for g in LIVING if g not in in_story and g not in used})
    for k in range(n_sub):
        g = foreign[k % len(foreign)]
        mat = mats_rank[k % len(mats_rank)]
        obj = sc['objects'][k % len(sc['objects'])] if (mat == 'object' and sc.get('objects')) else None
        obj_feat = obj.get('features') if obj else None
        # 자리: 재질과 이어진 사건(금속·전기·종이…)·오브제의 문장 둘레, 없으면 남은 자리
        if obj:
            ev = {'sentences': obj.get('sentences') or [], 'positions': obj.get('positions') or []}
        else:
            ev = (sc.get('events') or {}).get(MAT_EVENT.get(mat, ''), {})
        cand = [(uu, ss) for uu, ss in (ev.get('sentences') or [])] or [(uu, None) for uu in ev.get('positions') or []]
        if cand:
            u0, s = cand[(k * 2) % len(cand)]
        else:
            u0, s = slots[(n_in + k) % len(slots)]
        dur = min(float(rng.uniform(3.0, 5.5)), 0.6 * D)
        f, a = GESTURES[g](dur, sr, rng)
        y = timbre(mat, f, a, sr, rng, obj_feat)
        t0 = float(np.clip(u0 * D - dur / 3, min(lo, D - dur), max(0.0, hi - dur)))
        add(dry, synth_pan(_norm(y, 0.42 * (0.6 + 0.6 * d)), float(rng.uniform(-0.6, 0.6))), int(t0 * sr))
        tk = ('%s 실루엣' % obj['name']) if obj else TIMBRE_KO[mat]
        note(t0, dur, '음색 치환', '%s 몸짓 × %s 음색' % (GESTURE_KO[g], tk),
             '이야기에 없는 생물(%s)의 몸짓을 이 장면의 재질(%s)로 연주 — 재질로 우는 생물' % (GESTURE_KO[g], tk),
             (s, u0) if s else None)

    # ③ 변신 — 가장 많이 나온 사건 소리 → 첫 오브제 소리
    evs = sorted((sc.get('events') or {}).items(), key=lambda kv: -len(kv[1].get('positions') or []))
    if evs and sc.get('objects'):
        ka, ea = evs[0]
        o = sc['objects'][0]
        ca = mats['event'].get(ka, [])
        cb = mats['object'].get(o['idx'], []) + ([mats['drone'][o['idx']]] if o['idx'] in mats['drone'] else [])
        if ca and cb:
            W = min(float(np.clip(0.12 * D, 4.0, 12.0)), 0.5 * D)
            ua = (ea.get('positions') or [0.4])[0]
            ub = (o.get('positions') or [0.6])[-1]
            uc = float(np.clip((ua + ub) / 2, W / D / 2, 1 - W / D / 2))
            A = _stretch_to(ca, W, sr, rng)
            B = _stretch_to(cb, W, sr, rng)
            y = morph(A, B, sr) * np.hanning(int(W * sr))[:len(A)]
            t0 = uc * D - W / 2
            add(dry, synth_pan(_norm(y, 0.40 * (0.5 + 0.7 * d)), 0.0), int(t0 * sr))
            from .read import EVENT_NAME
            note(t0, W, '변신', '%s → %s (%.0f초에 걸쳐)' % (EVENT_NAME.get(ka, ka), o['name'], W),
                 '한 소리가 다른 오브제의 소리로 서서히 바뀜 — 배경 화면의 점진적 모핑과 같은 원리', None)

    # ④ 데자뷔 — 앞에서 들린 사건이 뒤에서 느리게·거꾸로·멀리
    if d >= 0.35:
        rep = [(k, e) for k, e in evs if len(e.get('positions') or []) >= 1 and min(e['positions']) < 0.5]
        if rep:
            k, e = rep[0]
            clips = mats['event'].get(k, [])
            if clips:
                u1 = min(e['positions'])
                u2 = max(0.72, max(e['positions']) + 0.05)
                if u2 < 0.97:
                    y = synth.pitch(clips[0], -7)[::-1]
                    y = synth.lowpass(np.concatenate([y, np.zeros(int(0.5 * sr))]), 1800, sr)
                    t0 = u2 * D
                    add(dry, synth_pan(_norm(y, 0.32), float(rng.uniform(-0.3, 0.3))), int(t0 * sr))
                    first = next((s for uu, s in (e.get('sentences') or []) if abs(uu - u1) < 1e-3), None)
                    from .read import EVENT_NAME
                    note(t0, len(y) / sr, '데자뷔', '%s 느리게·거꾸로 되돌아옴' % josa(EVENT_NAME.get(k, k), '이', '가'),
                         '장면 앞(%.0f초)에서 들린 소리가 기억처럼 멀리서 되풀이됨' % (u1 * D),
                         (first, u1) if first else None)


def synth_pan(y, p):
    a = (p + 1) * math.pi / 4
    return np.stack([y * math.cos(a), y * math.sin(a)], axis=1)
