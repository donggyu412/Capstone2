"""1단계 · 읽기 — 장면 하나에서 '언제 · 어떤 음색으로 · 무슨 소리가' 날지를 읽는다.

  ① 이야기 문장 → 언제     문장이 글의 어디쯤인가(0~1) = 장면 안의 시각. 동작·재질 낱말 분류표로 사건(물방울·종이·균열…)을
                           찾고, 그 문장 자리에 놓는다. 꿈의 물리 법칙(빨라짐·삼켜짐…)과 정적 문장도 여기서 읽는다.
                           분류표에 없는 낱말(손 · 글씨 · 가슴 · 가죽끈…)도 '그 낱말이 가리키는 소리'로 (WORD_SOUNDS)
  ② 그림 수치 → 음색       배경 사진의 밝기·대비·암부·윤곽 → 공간과 방의 공기(룸톤)
                           오브제 실루엣의 면적·각짐·대칭·밝기 → 울림(모달 합성)의 음높이·배음·감쇠
                           (교차감각 대응 — 밝을수록 높고, 클수록 낮고, 각질수록 날카롭게)
  ③ 그림 인식 → 무슨 소리  vision.py — 배경에 보이는 소리 낼 물체(형광등·창문·시계…)와 그 위치·거리,
                           오브제가 무엇인지(책 → 종이 넘기는 소리), 재질, 장소 → 이 소리들도 재생된다
  + 분위기                배경 그림의 밝기·색온도·채도 + 이야기 감정 → 4단계 작곡의 선법·화성
어느 것도 특정 오브제·특정 스토리에 묶이지 않는다(새 스토리가 와도 코드 수정 없음).
"""
import ast
import json
import math
import os
import re

import numpy as np
from PIL import Image

from . import paths

ACT_KEYS = ['기', '승', '전', '결']

# ── ① 스토리 글 → 소리 사건 ─────────────────────────────────────────────
# (키, 이름, [낱말], 영어 묘사, 기본 빈도(10초당 사건 수))
# 낱말은 '흔한 글자'를 피했다: '금'(금속·지금) 대신 '금이·금은·금들', '발'(발끝) 대신 '발자국·걸음'.
EVENT_RULES = [
    ('drip',     '물방울',   ['물방울', '떨어진다', '떨어지', '방울', '똑똑', '빗물'],
     'water droplets dripping into a shallow puddle, echoing', 6.0),
    ('electric', '전기 험',  ['형광등', '깜박', '알전구', '전구', '전등', '불빛'],
     'faint electrical hum and buzz of a flickering old light', 1.5),
    ('creak',    '삐걱임',   ['삐걱', '흔들리', '흔들며', '흔들림', '흔들린'],
     'slow creaking of old metal and wood, swaying', 1.5),
    ('rustle',   '종이',     ['종이', '팔락', '넘어가', '넘겨', '넘기', '바스락', '서류', '책장', '페이지', '낱장'],
     'rustling and flipping of old paper pages', 3.0),
    ('crack',    '균열',     ['금이', '금은', '금들', '금 틈', '금 사이', '갈라', '파열', '바스러', '부서', '균열', '실금', '벌어',
                             '깨지', '깨진', '깨져', '깨어', '산산', '부러'],
     'sharp brittle cracking of ceramic tiles', 2.0),
    ('liquid',   '액체',     ['웅덩이', '냉동액', '액체', '젖어', '물결', '잔물결', '걸쭉'],
     'viscous cold liquid, slow bubbling and dripping', 2.0),
    ('ice',      '냉기',     ['얼음', '냉기', '서리', '차갑', '서늘', '얼어', '굳어', '소름'],
     'glassy cold shimmer, frozen air', 1.0),
    ('breath',   '숨·공기',  ['숨을', '숨이', '숨 ', '공기', '호흡', '목 안쪽', '헐떡', '김이', '김 서', '증기', '입김'],
     'slow heavy breathing, low stale air movement', 1.0),
    ('wind',     '바람',     ['바람', '갈대', '휘파람', '폭풍', '돌풍', '휘몰아', '나부끼'],
     'cold wind gusting through reeds, faint whistling', 1.0),
    ('rain',     '비',       ['비가', '빗방울', '빗소리', '빗줄기', '소나기', '빗물', '이슬비'],
     'steady rain pattering on glass and roof', 1.0),
    ('snow',     '눈',       ['눈이 내', '눈송이', '눈발', '눈보라', '함박눈', '눈 덮인', '눈밭'],
     'soft falling snow, muffled hush, tiny crystal ticks', 0.8),
    ('knock',    '두드림',   ['두드리', '두드린', '두들기', '노크', '똑똑', '톡톡'],
     'knocking on wood and glass, hollow taps', 2.0),
    ('door',     '문',       ['문이', '문을', '문 틈', '열리', '닫히', '닫힌', '덜컹', '자물쇠', '열쇠'],
     'old heavy door opening and closing, latch clicks', 1.0),
    ('alarm',    '경보·신호음', ['경보', '사이렌', '알람', '신호음', '삐-', '삐익', '비프', '경고음'],
     'distant low electronic alarm tone, pulsing', 1.0),
    ('machine',  '기계',     ['기계', '모터', '엔진', '윙윙', '톱니', '로봇', '환풍기', '발전기'],
     'low mechanical hum, servo motors whirring', 1.0),
    ('clock',    '시계',     ['시계', '째깍', '초침', '똑딱', '태엽'],
     'ticking clock mechanism, close and dry', 4.0),
    ('flow',     '흐르는 물', ['흐르', '물소리', '시냇', '파도', '물살', '쏟아', '넘쳐'],
     'flowing water, gentle stream and lapping waves', 1.0),
    ('fire',     '불',       ['불꽃', '타오르', '타닥', '장작', '불길', '그을', '타는'],
     'crackling fire, embers popping', 2.0),
    ('glass',    '유리',     ['유리', '쨍그랑', '크리스탈', '거울', '창문'],
     'glass resonance, delicate high ping', 1.5),
    ('animal',   '동물 소리', ['짖', '울음', '새소리', '새 소리', '새들', '지저귀', '울부짖', '까마귀', '고양이', '늑대', '벌레 소리'],
     'distant animal call echoing, far away', 0.8),
    ('metal',    '금속',     ['철판', '철제', '녹슨', '녹이', '쇠', '금속', '쇳가루'],
     'resonant rusty metal plate, low metallic groan', 1.5),
    ('thump',    '둔탁',     ['둔탁', '진동', '꺼졌', '꺼진다', '쿵', '발자국', '걸음', '내려앉'],
     'dull distant thud, low vibration through the floor', 1.5),
    ('friction', '마찰',     ['마찰', '긁', '스치', '문지', '눌어붙', '끌린'],
     'low scraping friction, dry rubbing', 1.5),
    ('presence', '존재감',   ['그림자', '형상', '형체', '어둠', '손끝', '창백한'],
     'ominous low presence, distant unsettling drone', 0.5),
]
EVENT_KEYS = [r[0] for r in EVENT_RULES]
EVENT_EN = {r[0]: r[3] for r in EVENT_RULES}
EVENT_NAME = {r[0]: r[1] for r in EVENT_RULES}
EVENT_RATE = {r[0]: r[4] for r in EVENT_RULES}

# ── 낱말 소리 (10-08) — 위 분류표에 없는 낱말도 '그 낱말이 가리키는 소리'로 ─────────────────
# 예: 손 · 손끝 → 손이 스치는 소리 / 글씨 · 잉크 → 펜촉 긁힘 / 가슴 → 박동 / 가죽끈 · 매듭 → 천 스침
# 장면의 이야기 사건에 이미 같은 소리가 있으면 겹치지 않게 뺀다. 장면당 많이 나온 순으로 최대 WORD_MAX 종류.
# (키, 소리 이름, [낱말]) — 키는 synth.EVENT_SYNTH 의 합성기 이름
WORD_SOUNDS = [
    ('touch',     '손 스침',     ['손끝', '손가락', '손바닥', '손목', '손등', '손을', '손이', '손은', '손 하나', '살갗', '피부', '손자국']),
    ('pen',       '글씨 긁힘',   ['글씨', '잉크', '글자', '숫자', '적혀', '적힌', '좌표', '날짜']),
    ('dust',      '먼지 사각임', ['먼지', '가루', '흙먼지', '재처럼']),
    ('tap',       '작은 쇠붙이 톡', ['압정', '단추', '못이', '핀으로', '동전']),
    ('heartbeat', '박동',       ['가슴', '심장', '맥박', '고동', '정맥']),
    ('cloth',     '천 스침',     ['가죽끈', '매듭', '소매', '옷자락', '커튼', '팔꿈치', '어깨', '팔이', '팔은']),
    ('knock',     '벽 · 타일 두드림', ['벽을', '벽은', '벽에', '벽이', '타일', '시멘트']),
    ('creak',     '선반 삐걱임', ['선반', '의자', '계단', '사다리']),
    ('thump',     '발소리',     ['발끝', '발밑', '밟을', '디딜', '발을', '종아리']),
    ('liquid',    '물',         ['물에', '물보다', '물이', '물을']),
    ('rustle',    '표지 · 책장', ['표지', '책장', '장이', '마지막 장']),
]
WORD_NAME = {k: n for k, n, _ in WORD_SOUNDS}
WORD_MAX = 6


def read_words(story, events):
    """이야기 → {소리키: {name, words, positions, sentences, hits}} — 사건 분류표가 이미 낸 소리는 뺀다."""
    out = {}
    for key, name, words in WORD_SOUNDS:
        if key in events:
            continue
        pos, ss, hit = [], [], set()
        for st, u in split_sentences(story):
            found = [w for w in words if mentions(st, w)]
            if found:
                pos.append(round(u, 3))
                ss.append([round(u, 3), st])
                hit.update(w.strip() for w in found)
        if pos:
            out[key] = {'name': name, 'words': sorted(hit), 'positions': pos, 'sentences': ss, 'hits': len(pos)}
    top = sorted(out.items(), key=lambda kv: -kv[1]['hits'])[:WORD_MAX]
    return dict(top)


# 정적(소리의 부재)은 사건이 아니라 '비움' — 그 위치에서 전체 음량을 낮춘다
SILENCE_WORDS = ['소리 없이', '소리도 없이', '정적', '고요', '적막', '침묵', '들리지 않', '거의 들리지']

# ── 꿈의 물리 법칙 중 '소리에 관한 것' → 렌더링 규칙 ─────────────────────────
# 3팀 배경(app.py LAW_RULES)은 소리 법칙을 '사운드 담당이 정해질 때까지' 남겨 두었다 — 그 빈칸을 채운다.
# 문장이 [A 중 하나]와 [B 중 하나]를 모두 가질 때만 (app.py 와 같은 방식) · 바로 뒤가 '지 않'이면 부정으로 본다.
SOUND_LAWS = [
    # 키           이름                A                                   B
    ('reverse',    '원인보다 먼저 오는 소리', ['먼저', '앞서', '전에'],          ['소리', '파열', '균열', '금이']),
    ('accel',      '빨라지는 간격',      ['간격', '박자', '소리'],            ['빨라', '줄어', '연동', '좁아']),
    ('space_link', '소리와 공간의 연동', ['크기', '넓어', '멀어', '거리'],     ['소리', '간격', '연동']),
    ('swallow',    '삼켜지는 소리',      ['소리 없이', '소리도 없이'],        ['사라', '떨어', '내려앉', '']),
    ('uneven',     '매번 다른 크기',     ['크기는 매번', '매번 다르', '크게 울리'], ['']),
    ('sink',       '낮아지는 소리',      ['소리는 점점 낮아', '낮아져', '잦아들'], ['']),
]


def _says(text, word):
    """text 가 word 를 긍정으로 말하는가 — '변하지 않음' 같은 부정을 거른다 (app.py says 와 같은 규칙)."""
    if not word:
        return True
    for m in re.finditer(re.escape(word), text):
        tail = text[m.end():m.end() + 4]
        if not tail.startswith(('지 않', '지 못')):
            return True
    return False


def mentions(sentence, word):
    """문장이 이 낱말의 소리를 '실제로' 말하는가.
    10-07 새 스토리 시험에서 찾은 오탐을 거른다:
      · 비유   '유리처럼 매끄럽고' · '파도처럼 흐트러졌고' — 바로 뒤가 처럼/같이/같은
      · 부정   '바람도 없는 복도' · '바람이 불지 않' — 바로 뒤 6글자 안에 없/않"""
    for m in re.finditer(re.escape(word), sentence):
        tail = sentence[m.end():m.end() + 6]
        if tail.lstrip().startswith(('처럼', '같이', '같은', '같다')):
            continue
        if re.match(r'^[가-힣]{0,2}\s?(?:없|않|못)', tail):
            continue
        return True
    return False


def split_sentences(story):
    """글 → [(문장, 0~1 위치)]. 위치는 문장 가운데 글자가 전체 글의 어디쯤인가 — 장면 안 시간 위치로 쓴다."""
    if not isinstance(story, str) or not story.strip():
        return []
    out, total = [], max(1, len(story))
    for m in re.finditer(r'[^.!?。\n]+[.!?。]?', story):
        s = m.group().strip()
        if len(s) >= 2:
            out.append((s, (m.start() + m.end()) / 2 / total))
    return out


def read_events(story, laws):
    """스토리·법칙 → {사건키: {hits, weight, positions, evidence}}, 정적 위치, 소리 법칙."""
    sents = split_sentences(story)
    events = {}
    for key, name, words, en, rate in EVENT_RULES:
        pos, ev, ss = [], [], []
        for s, u in sents:
            if any(mentions(s, w) for w in words):
                pos.append(round(u, 3))
                ss.append([round(u, 3), s])
                if len(ev) < 2:
                    ev.append(s)
        if pos:
            events[key] = {'name': name, 'hits': len(pos), 'positions': pos, 'evidence': ev, 'sentences': ss}
    total = sum(e['hits'] for e in events.values()) or 1
    for e in events.values():
        e['weight'] = round(e['hits'] / total, 3)
    silence = [[round(u, 3), s] for s, u in sents if any(w in s for w in SILENCE_WORDS)]

    texts = [p for p in (laws or []) if isinstance(p, str)] + [s for s, _ in sents]
    found = []
    for key, name, a, b in SOUND_LAWS:
        for t in texts:
            if any(w in t for w in a) and any(_says(t, w) for w in b):
                found.append({'key': key, 'name': name, 'src': t})
                break
    return events, silence, found


# ── ④ 감정 → 정서가(valence)·각성(arousal) ─────────────────────────────────
# Russell(1980) 원형 모델 위의 대략적 좌표. 1팀 7종(09-27 확정)을 받는다.
EMO_VA = {
    '기쁨': (0.8, 0.5), '슬픔': (-0.7, -0.4), '분노': (-0.6, 0.8), '공포': (-0.7, 0.7),
    '놀람': (0.2, 0.8), '혐오': (-0.6, 0.3), '중립': (0.0, 0.0),
}
EMO_FALLBACK = [('불안', '공포'), ('두려', '공포'), ('공포', '공포'), ('무서', '공포'), ('긴장', '공포'),
                ('우울', '슬픔'), ('슬픔', '슬픔'), ('상실', '슬픔'), ('고립', '슬픔'), ('공허', '슬픔'),
                ('분노', '분노'), ('혐오', '혐오'), ('불쾌', '혐오'), ('놀라', '놀람'), ('경이', '놀람'),
                ('기쁨', '기쁨'), ('행복', '기쁨'), ('평온', '중립'), ('스산', '공포'), ('압박', '공포')]


def read_emotion(row):
    v = row.get('main_emotion') or row.get('emotion')
    label, inten, src = None, None, None
    if isinstance(v, dict):
        label = v.get('label') or v.get('emotion')
        try:
            inten = float(v.get('intensity', v.get('value')))
        except (TypeError, ValueError):
            inten = None
        src = 'main_emotion'
    elif isinstance(v, str):
        label, src = v.strip(), 'main_emotion'
    if label not in EMO_VA:
        phrases = row.get('emotions') or []
        phrases = [phrases] if isinstance(phrases, str) else phrases
        hit = None
        for ph in ([label] if label else []) + list(phrases):
            if isinstance(ph, str):
                c = [(ph.find(k), lab) for k, lab in EMO_FALLBACK if k in ph]
                if c:
                    hit = min(c)[1]
                    src = 'emotions 문장: ' + ph
                    break
        label = hit or '중립'
    inten = 0.7 if inten is None else max(0.0, min(1.0, inten))
    va, ar = EMO_VA[label]
    return {'label': label, 'intensity': inten, 'valence': round(va * inten, 3),
            'arousal': round(ar * inten, 3), 'src': src}


# ── ② 배경 사진 → 공간 특징 ──────────────────────────────────────────────
def _load_rgb(path, width=320):
    im = Image.open(path)
    im = im.convert('RGBA') if im.mode in ('RGBA', 'LA', 'P') else im.convert('RGB')
    if im.width > width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.BILINEAR)
    return np.asarray(im).astype(np.float32) / 255.0


def _hsv(rgb):
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6.0
    return h, sat, mx


def image_features(path):
    """배경 사진 → 공간 음향 목표를 정할 수치 (전부 0~1)."""
    a = _load_rgb(path)[..., :3]
    L = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    _, sat, _ = _hsv(a)
    gy, gx = np.gradient(L)
    edge = np.hypot(gx, gy)
    h, w = L.shape
    cy0, cy1, cx0, cx1 = h // 3, 2 * h // 3, w // 3, 2 * w // 3
    center = L[cy0:cy1, cx0:cx1].mean()
    ring = (L.sum() - L[cy0:cy1, cx0:cx1].sum()) / max(1, L.size - L[cy0:cy1, cx0:cx1].size)
    return {
        'luma': round(float(L.mean()), 4),                       # 밝기 → 음의 밝기·높이
        'contrast': round(float(L.std()), 4),                    # 대비 → 다이내믹스
        'dark': round(float((L < 0.15).mean()), 4),              # 암부 → 저역·잔향
        'bright': round(float((L > 0.75).mean()), 4),            # 밝은 곳 → 고역 반짝임
        'saturation': round(float(sat.mean()), 4),               # 채도 → 음색의 '색'(배음 선명도)
        'warmth': round(float((a[..., 0] - a[..., 2]).mean()), 4),   # 난색(+)/한색(−)
        'edges': round(float(min(1.0, edge.mean() * 12)), 4),    # 윤곽 밀도 → 결의 촘촘함·사건 밀도
        'depth': round(float(np.clip((center - ring) * 3 + 0.5, 0, 1)), 4),  # 가운데가 밝은 복도 = 깊은 공간 → 긴 잔향
        'size': [int(w), int(h)],
    }


# ── ③ 오브제 PNG → 형태 특징 ──────────────────────────────────────────────
def object_features(path):
    """투명 PNG(rembg 결과) → 실루엣·색 수치. 알파가 없으면 흰 바탕이 아닌 곳을 형체로 본다."""
    from scipy import ndimage
    a = _load_rgb(path, width=256)
    if a.shape[-1] == 4:
        mask = a[..., 3] > 0.5
    else:
        mask = a[..., :3].min(-1) < 0.92
    rgb = a[..., :3]
    area = float(mask.mean())
    if mask.sum() < 20:
        return {'area': area, 'empty': True}
    ys, xs = np.nonzero(mask)
    bh, bw = int(np.ptp(ys)) + 1, int(np.ptp(xs)) + 1
    # 둘레 = 형체 안이면서 이웃 중 하나가 바깥인 픽셀
    er = ndimage.binary_erosion(mask)
    perim = float((mask & ~er).sum())
    compact = float(min(1.0, 4 * math.pi * mask.sum() / max(1.0, perim) ** 2))   # 원 = 1, 들쭉날쭉 = 0
    try:
        from scipy.spatial import ConvexHull
        pts = np.column_stack([xs, ys])
        if len(pts) > 4000:
            pts = pts[np.linspace(0, len(pts) - 1, 4000).astype(int)]
        hull = ConvexHull(pts)
        solidity = float(min(1.0, mask.sum() / max(1.0, hull.volume)))
    except Exception:
        solidity = compact
    sub = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    sym = float((sub & sub[:, ::-1]).sum() / max(1, (sub | sub[:, ::-1]).sum()))
    lab, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, lab, range(1, n + 1)) if n else []
    parts = int(sum(1 for s in sizes if s > 0.002 * mask.sum()))
    L = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2])[mask]
    hue, sat, _ = _hsv(rgb)
    hs = hue[mask]
    hue_mean = float((math.atan2(np.sin(hs * 2 * math.pi).mean(), np.cos(hs * 2 * math.pi).mean()) / (2 * math.pi)) % 1)
    return {
        'area': round(area, 4),                                   # 클수록 낮은 음
        'aspect': round(float(bh / max(1, bw)), 3),               # 세로로 길수록 길게 끌리는 소리
        'angularity': round(float(np.clip(1 - 0.5 * (compact + solidity), 0, 1)), 4),  # 각질수록 날카롭고 비조화
        'solidity': round(solidity, 4),
        'symmetry': round(sym, 4),                                # 대칭일수록 조화로운 배음
        'parts': parts,                                           # 흩어진 조각 = 여러 개의 작은 사건
        'luma': round(float(L.mean()), 4),                        # 밝을수록 높은 음
        'saturation': round(float(sat[mask].mean()), 4),
        'hue': round(hue_mean, 4),
        'warmth': round(float((rgb[..., 0] - rgb[..., 2])[mask].mean()), 4),
    }


# ── 입력 찾기 ────────────────────────────────────────────────────────────
def pick_storyboard(path=None):
    """스토리보드 json — 지정이 없으면 배경 폴더의 가장 최근 json (배경 app.py 와 같은 규칙)."""
    if path:
        return path
    d = paths.STORYBOARD_DIR
    found = [os.path.join(d, n) for n in os.listdir(d) if n.lower().endswith('.json')] if os.path.isdir(d) else []
    if not found:
        raise SystemExit('스토리보드 json 을 찾지 못했습니다: %s (--scenes 로 지정)' % paths.rel(d))
    return max(found, key=os.path.getmtime)


def _scene_number(v):
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r'\d+', str(v or ''))
    return int(m.group()) if m else None


def load_scenes(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get('scenes') or data.get('장면') or []
    rows = [r for r in data if isinstance(r, dict)]
    nums = [_scene_number(r.get('scene', r.get('act'))) for r in rows]
    if None in nums or len(set(nums)) != len(nums):
        nums = list(range(1, len(rows) + 1))       # 번호가 없거나 겹치면 배열 순서로
    for r, n in zip(rows, nums):
        r['_num'] = n
    return sorted(rows, key=lambda r: r['_num'])


def find_background(num, folder):
    for ext in paths.IMAGE_EXT:
        p = os.path.join(folder, 'scene_%02d%s' % (num, ext))
        if os.path.exists(p):
            return p
    return None


def object_english_map():
    """오브제 팀 코드의 OBJ_ENGLISH_MAP 을 '실행하지 않고' 읽는다 (rembg·ComfyUI 없이도 되게 ast 로)."""
    for name in ('generate_objects_comfy.py', 'prepare_dataset.py'):
        p = os.path.join(paths.OBJECT_DIR, name)
        if not os.path.exists(p):
            continue
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'OBJ_ENGLISH_MAP' for t in node.targets):
                    return ast.literal_eval(node.value)
        except (SyntaxError, ValueError, OSError):
            pass
    return {}


def find_objects(rows, folder=None):
    """오브제 이미지 → {장면번호: [(한글 이름, 경로)]}.

    ① output_objects/scene_N/obj_k_이름.png  — 장면·이름이 파일명에 있다 (오브제 코드 원래 출력)
    ② dataset/10_dream_object/obj_XX.png+txt — 이름이 지워져 캡션(영어)으로 거꾸로 찾는다
       캡션 → OBJ_ENGLISH_MAP 역변환 → 한글 이름 → 그 이름을 objects 에 가진 장면
    둘 다 없으면 빈 값 — 오브제 층 없이 배경·글로만 만든다."""
    base = folder or paths.OBJECT_DIR
    out, notes = {}, []
    names_by_scene = {r['_num']: [o for o in (r.get('objects') or []) if isinstance(o, str)] for r in rows}
    oo = os.path.join(base, 'output_objects')
    if os.path.isdir(oo):
        for d in sorted(os.listdir(oo)):
            n = _scene_number(d)
            if n is None or not os.path.isdir(os.path.join(oo, d)):
                continue
            for f in sorted(os.listdir(os.path.join(oo, d))):
                if f.lower().endswith(paths.IMAGE_EXT):
                    nm = re.sub(r'^obj_\d+_', '', os.path.splitext(f)[0]).replace('_', ' ')
                    out.setdefault(n, []).append((nm, os.path.join(oo, d, f)))
        if out:
            return out, ['오브제: output_objects/ (장면·이름을 파일명에서 읽음)']
    ds = None
    for root, dirs, files in os.walk(base):
        if any(f.lower().endswith('.txt') for f in files) and any(f.lower().endswith('.png') for f in files):
            ds = root
            break
    if ds is None:
        return {}, ['오브제 이미지 없음 — 오브제 층 없이 진행 (%s)' % paths.rel(base)]
    rev = {v.strip().lower(): k for k, v in object_english_map().items()}
    used = set()
    for f in sorted(os.listdir(ds)):
        if not f.lower().endswith('.png'):
            continue
        txt = os.path.join(ds, os.path.splitext(f)[0] + '.txt')
        cap = open(txt, encoding='utf-8').read() if os.path.exists(txt) else ''
        parts = [p.strip() for p in cap.split(',')]
        desc = parts[1] if len(parts) > 1 else ''
        ko = rev.get(desc.lower())
        if not ko:
            notes.append('%s: 캡션 "%s" 을 한글 이름으로 되돌리지 못함 — 건너뜀' % (f, desc))
            continue
        # 정확히 같은 이름 → 없으면 그 이름을 품은 더 긴 이름('서류철' → '밤색 서류철').
        # prepare_dataset.py 는 파일명에 '서류철'이 들어 있으면 먼저 나온 짧은 키로 캡션을 단다 —
        # 그래서 '밤색 서류철' 그림이 'document folder' 캡션을 달고 온다(10-06 확인). 이미 쓴 이름이면 긴 쪽으로 넘긴다.
        cands = [(n, nm) for n, names in names_by_scene.items() for nm in names if nm == ko]
        cands += [(n, nm) for n, names in names_by_scene.items() for nm in names if nm != ko and ko in nm]
        for n, nm in cands:
            if (n, nm) not in used:
                used.add((n, nm))
                out.setdefault(n, []).append((nm, os.path.join(ds, f)))
                if nm != ko:
                    notes.append('%s: 캡션은 "%s" 지만 이미 연결돼 "%s" 로 연결 (prepare_dataset 캡션 겹침)' % (f, ko, nm))
                break
        else:
            notes.append('%s: "%s" 는 이번 스토리보드에 없는 오브제 — 건너뜀' % (f, ko))
    notes.insert(0, '오브제: %s (캡션으로 장면 역추적, %d장 연결)' % (paths.rel(ds), sum(len(v) for v in out.values())))
    return out, notes


def object_positions(name, story):
    """오브제가 글의 어디서 나오나 — 머리 명사('얼음을 쪼는 검은 새' → 새)가 들어간 문장들의 위치."""
    words = re.sub(r'\(.*?\)', '', name).split()
    head = words[-1] if words else name          # '창백하고 얇은 손' → '손' (한 글자여도 머리 명사)
    keys = [w for w in words[:-1] if len(w) >= 2]
    hit = [[round(u, 3), s] for s, u in split_sentences(story) if head in s]
    if not hit:
        hit = [[round(u, 3), s] for s, u in split_sentences(story) if any(k in s for k in keys)]
    return hit


# ── 분위기: 배경 그림 + 이야기 감정 → 정서가·각성 (4단계 작곡이 쓴다) ─────────────
# 색–정서 대응: 밝을수록·따뜻할수록 긍정, 채도·대비가 클수록 각성 (Jonauskaite et al. 2020 · Valdez & Mehrabian 1994†)
PLACE_MOOD = {'forest': (0.2, -0.1), 'field': (0.3, -0.1), 'water': (0.15, -0.2), 'cave': (-0.25, 0.1),
              'basement': (-0.25, 0.1), 'corridor': (-0.1, 0.05), 'bathroom': (-0.1, 0.1), 'street': (-0.1, 0.1)}
BG_WEIGHT = 0.65          # 작곡은 '배경의 분위기'를 따른다 — 이야기 감정은 35% 만 섞는다


def background_mood(bg, place=None):
    if not bg:
        return None
    v = 1.6 * (bg['luma'] - 0.3) + 1.2 * bg['warmth'] + 0.5 * (bg['saturation'] - 0.25) - 0.6 * bg['dark']
    a = 1.4 * (bg['saturation'] - 0.25) + 1.5 * (bg['contrast'] - 0.15) - 0.5 * (bg['luma'] - 0.3) + 0.6 * bg['edges'] - 0.2
    if place:
        dv, da = PLACE_MOOD.get(place[0], (0, 0))
        w = min(1.0, place[2] / 0.4)
        v, a = v + dv * w, a + da * w
    return float(np.clip(v, -1, 1)), float(np.clip(a, -1, 1))


def mood(scene):
    e = scene['emotion']
    pl = ((scene.get('vision') or {}).get('place') or [None])[0]
    bm = background_mood((scene.get('background') or {}).get('features'), pl)
    if bm is None:
        return {'valence': e['valence'], 'arousal': e['arousal'], 'bg': None, 'src': '이야기 감정만 (배경 사진 없음)'}
    v = BG_WEIGHT * bm[0] + (1 - BG_WEIGHT) * e['valence']
    a = BG_WEIGHT * bm[1] + (1 - BG_WEIGHT) * e['arousal']
    return {'valence': round(v, 3), 'arousal': round(a, 3), 'bg': [round(bm[0], 3), round(bm[1], 3)],
            'src': '배경 그림 %d%% (밝기·색온도·채도·대비%s) + 이야기 감정 %s %d%%' % (
                100 * BG_WEIGHT, ' · 장소 ' + pl[1] if pl else '', e['label'], 100 * (1 - BG_WEIGHT))}


def read(scenes_path=None, bg_folder=None, obj_folder=None, vision_mode='auto', log=print):
    """1단계 전체 → (장면 목록, 메모, 그림 인식 요약 또는 None)."""
    scenes, notes = analyze(scenes_path, bg_folder, obj_folder)
    en = object_english_map()
    from . import synth
    for s in scenes:
        empty = [o['name'] for o in s['objects'] if o['features'].get('empty')]
        if empty:
            notes.append('장면 %d: 형체가 거의 없는 오브제 그림 제외 — %s' % (s['num'], ', '.join(empty)))
        s['objects'] = [o for o in s['objects'] if not o['features'].get('empty')]
        for i, o in enumerate(s['objects']):
            o['idx'] = i
            o['name_en'] = en.get(o['name'])
            o['pitch_offset'] = round(float(synth.rng_for(o['name']).uniform(-1, 1)), 3)   # 같은 이름 = 같은 음높이 결
    vis = None
    if vision_mode != 'off':
        from . import vision
        err = '모델을 하나도 불러오지 못함'
        try:
            vis = vision.annotate(scenes, log=log, require=vision_mode == 'on')
        except Exception as e:                      # auto 면 그림 인식 없이 계속, on 이면 멈춘다
            err = str(e)[:300]
            log('그림 인식 건너뜀 — %s' % err)
        if vision_mode == 'on' and vis is None:
            raise SystemExit('그림 인식을 쓰지 못했습니다: %s\n'
                             '  · pip install -r team3/sound/requirements-gpu.txt (CUDA torch 먼저)\n'
                             '  · 처음 한 번은 Hugging Face 에서 모델을 내려받습니다(약 2.5GB, 로그인 필요 없음)\n'
                             '  · 그림 인식 없이 돌리려면 --vision off' % err)
    from .vision import object_identity
    for s in scenes:
        for o in s['objects']:
            if not o.get('identity'):
                o['identity'] = object_identity(None, o.get('name_en'))     # 그림 인식이 없으면 오브제 팀 영어 이름표로
        s.setdefault('seen', [])
        s['mood'] = mood(s)
    return scenes, notes, vis


def analyze(scenes_path=None, bg_folder=None, obj_folder=None):
    """전체 분석 → (장면 목록, 메모). 장면 하나 = 이후 단계가 쓰는 모든 수치."""
    path = pick_storyboard(scenes_path)
    rows = load_scenes(path)
    bg_folder = bg_folder or os.path.dirname(path)
    objs, notes = find_objects(rows, obj_folder)
    notes.insert(0, '스토리보드: %s (%d장면)' % (paths.rel(path), len(rows)))
    scenes = []
    n = len(rows)
    for i, r in enumerate(rows):
        num = r['_num']
        story = r.get('story') if isinstance(r.get('story'), str) else ''
        stage = r.get('stage') if r.get('stage') in ACT_KEYS else ACT_KEYS[min(3, i * 4 // max(1, n))]
        events, silence, laws = read_events(story, r.get('physics_laws'))
        bg_path = find_background(num, bg_folder)
        if not bg_path:
            notes.append('장면 %d: 배경 사진 scene_%02d.png 없음 — 글만으로 공간을 정함' % (num, num))
        obj_list = []
        for ko, p in objs.get(num, []):
            hit = object_positions(ko, story)
            obj_list.append({'name': ko, 'path': p, 'features': object_features(p),
                             'positions': [u for u, _ in hit], 'sentences': hit})
        scenes.append({
            'num': num, 'stage': stage,
            'title': (r.get('backgrounds') or [None])[0] or r.get('title') or '장면 %d' % num,
            'backgrounds': [b for b in (r.get('backgrounds') or []) if isinstance(b, str)],
            'object_names': [o for o in (r.get('objects') or []) if isinstance(o, str)],
            'emotion': read_emotion(r),
            'events': events, 'words': read_words(story, events),
            'silence': [u for u, _ in silence], 'silence_sents': silence, 'laws': laws,
            'story': story,
            'background': {'path': bg_path, 'features': image_features(bg_path) if bg_path else None},
            'objects': obj_list,
        })
    return scenes, notes
