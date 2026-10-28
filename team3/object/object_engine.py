#!/usr/bin/env python3
"""
꿈 오브제 창발 엔진 — 시도 A (파티클)
캡스톤 디자인2 · 3팀 · 시스템 II (꿈 오브제)

오브제 PNG 를 그대로 띄우지 않는다. 투명 PNG 의 픽셀을 수천 개의 입자로 쪼개고,
입자들이 기승전결의 힘을 받으며 제자리를 찾아 '맺히고', 스토리의 물리 법칙대로 움직이다가 '풀린다'.

  무엇이 움직임을 정하나 (난수로 흐름을 정하지 않는다 — 스토리 기반)
    장면 순서        → 기·승·전·결 : 입자에 걸리는 힘의 종류 (ACTS)
    physics_laws    → 오브제별 동작 : 오브제가 주어인 법칙만 옮긴다 (LAW_RULES · GROUPS)
                      배경·소리 법칙은 배경 엔진·사운드 몫이라 건너뛰고 law_map.json 에 이유를 남긴다
    objects 순서    → 등장 순서 (스토리에 나오는 순서)
    main_emotion    → 색·난류에 얇게 곱한다 (EMOTIONS)
    입자 초기 배치  → 스토리 글로 만든 시드 — 같은 스토리면 같은 영상, 스토리가 바뀌면 바뀐다

  두 가지 출력
    오브제만     python object_engine.py
    배경과 통합  python object_engine.py --bg dream.mp4 --bg-json video.json --out integrated.mp4

  하나의 오브제 · 진화 (선화 기본 · 11/05 교수님 피드백) — targets.json 이 있으면 이 방식
    targets.py 로 오브제마다 Claude 가 그린 기하학적 선화(흰 윤곽 · 어긋난 색 선 · 그물망 · 감정에 맞는 표정)를 진화 목표로 삼는다.
    장면 1 은 랜덤 위치의 점 무리에서 시작해, 세대마다 변이 → 목표에 가까운 개체가 살아남는 진화로 목표 선화에 다가간다.
    이웃 개체가 목표 가까이 모이면 그 사이가 선으로 이어져 형상이 된다. 이야기에 다음 오브제가 나오면 무리가 흩어졌다가 다음 목표로 진화하고,
    형상이 갖춰진 뒤에도 꿈의 변형 · 큰 변이로 정적인 물체로 머물지 않는다.

  하나의 오브제 · 손그림 형상 (10/30 교수님 피드백) — targets.json 이 없고 doodles.json 이 있으면 이 방식
    대본의 오브제마다 알아볼 수 있는 손그림 형상(새 · 고양이 · 손 · 문 · 헬리콥터 …)을 고른다 — doodles.py
    (사람이 직접 그린 낙서 데이터셋 Quick, Draw! · CC BY 4.0 · 처음 한 번 형상마다 조금 내려받아 doodle_cache/ 에 둔다)
    형상은 처음엔 드러나지 않는다: 그 형상의 획들이 엉뚱한 자리 · 각도로 조각조각 그어졌다 지워지다가,
    그 오브제가 장면 이야기에 처음 나오는 자리에서 제자리를 찾아 드러나고, 다음 오브제가 나올 때까지
    조각으로 풀렸다가 다음 형상으로 모인다. 오브제 ↔ 이야기 설명서: <오브제 폴더>/object_story.md
    --doodle-llm : Claude 가 이야기 맥락까지 보고 형상을 고른다 · --no-doodles : 예전처럼 PNG 윤곽

  세 가지 그리기 방식 (--style)
    line     (기본 · 10/22 메인) 아래 설명 + 어린아이 로봇이 그리는 과정 —
             펜을 대고 망설이다가 획을 그리고, 그리다 멈칫하고, 비뚤게 그린 획은 멈추고 지우개로 지운 뒤 다시 그리고,
             가끔 한 번 더 덧그린다. 펜(밝은 점)과 지우개(빈 동그라미)가 화면에 보인다. 지우는 건 잘못 그은 획뿐이고,
             오브제는 장면의 80% 안에 완성되어 장면 끝까지 머물다가 마지막 2.5초에 부드럽게 사라진다. 크기는 장면 안에서도 숨쉬듯 바뀐다.
             그리는 순서 · 틀릴 획 · 멈칫할 자리는 스토리로 만든 시드로 정해져 같은 스토리면 같은 영상이 나온다.
    analog   부드러운 빛 입자 · 번짐 · 안개 — 아날로그 꿈
    digital  격자에 맞물리는 사각 블록 · 평평한 색 · 통통 튀는 조립 — 로봇의 꿈 (추상·기하·단순·원초적)
    line     굵은 손그림 선의 기하 도형 — 오브제 윤곽을 다각형·원으로 단순화하고, 물리 법칙을 덧그림 기호로
             (부유 = 물결 · 회전 = 나선 · 갈라짐 = 지그재그 · 바스러짐 = 흩어진 짧은 선 · 팔락임 = 옆 지그재그 …).
             획이 하나씩 그려졌다가 지워지고, 장면의 오브제 조각이 메아리처럼 작게 떠다닌다.
             기승전결에 따라 커졌다가(전 = 절정 · 반전 때 획이 화면 가득 터짐) 다시 작아진다. (교수님 10/15 예제 영상 방향)
    python object_engine.py --style line

  다른 팀에 넘길 때
    오브제만 + 투명도   python object_engine.py --alpha-out --out object_line.mp4
                        → object_line.mp4(검은 바탕 · 투명도를 곱한 색) + object_line_matte.mp4(흰색 = 오브제)
                        합성: out = bg × (1 − matte) + fill
    남의 배경 위에 합성 python object_engine.py --bg 배경.mp4 --bg-audio   (배경 영상의 소리를 그대로 붙인다)
    4팀용 두 가지를 한 번에: render_team4.py

  빠른 미리보기 (장면당 10초 · 절반 해상도)
    python object_engine.py --scene-sec 10 --scale 0.5 --out preview.mp4
    ※ 등장·반전은 75초 기준으로 맞춘 움직임이라, 짧은 미리보기에서는 실제보다 급하게 보인다

  10/15 반영 (교수님 10/8 검토)
    점에서 시작하는 등장 (--emerge point · 기본)
      오브제마다 한 점에서 출발 — 앞 장면 잔해 중 그 자리에 가장 가까운 한 점에서 태어난다.
      격자 8칸 → 4칸 → 2칸 → 1칸 간격 입자 순서로 태어나 '점 → 성긴 윤곽 → 촘촘한 전체'로 약 16초에 걸쳐 드러난다.
      오브제 사이 간격 7.5초 · 원본 윤곽은 거의 다 드러난 뒤에야 옅게 깔린다. 예전 방식은 --emerge cloud.
    전(轉) 장면 반전 (--reversal 0.6 · 기본 = 전 장면 시작 후 45초 · 4장면 5분이면 전체 3:15)
      모였던 오브제 전부가 한순간에 터지듯 흩어졌다가(약 1초), 위아래가 뒤집히고 1.15배 커지고
      감정 색조의 반대색으로 바뀐 채 약 3초 안에 다시 모인다. 반전 시각은 결과 json 의 "reversal" 에 적힌다
      (배경·사운드를 이 시각에 맞춘다). 끄려면 --no-reversal.
    밝은·색 배경 대비 (--contrast · 통합이면 기본 1, 오브제만이면 0)
      배경이 밝은 자리일수록 오브제 몸통 둘레에 부드러운 어두운 받침을 깔고(어두운 자리에는 거의 없음),
      오브제 밝기가 바로 뒤 배경 밝기와 일정 이상 벌어지도록 색은 지킨 채 밝기만 맞춘다. 번짐 빛도 밝은 배경에서는 줄인다.
    병렬 렌더 (--jobs auto · 기본)
      장면마다 따로 동시에 렌더해 이어 붙인다. 각 장면은 앞 장면을 그리지 않고 계산만 빨리 감은 뒤 시작해서,
      한 줄로 돌린 것과 화소 단위로 같은 결과가 나온다(무손실 비교로 확인). 한 줄로 돌리려면 --jobs 1.

필요 패키지: pip install numpy pillow opencv-python imageio-ffmpeg
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────
# 1. 기승전결 — 막마다 입자에 걸리는 힘의 종류
#    settle 제자리로 끌리는 힘 · fric 마찰(1에 가까울수록 미끄럽다) · turb 난류
#    swirl 오브제 중심을 도는 힘 · glow 번짐 빛 · ghost 원본 윤곽(옅게) · fog 안개
#    dissolve 풀리기 시작하는 시점(장면 안 비율)
# ─────────────────────────────────────────────────────────────
ACT_NAMES = ['기', '승', '전', '결']
RELEASE_SPAN = 0.10  # 풀리기 시작해서 마지막 입자가 놓일 때까지 (장면 안 비율)
ACTS = {
    '기': dict(settle=0.022, fric=0.90, turb=1.00, swirl=0.00, glow=0.80, ghost=0.07, fog=0.10, spread=1.00, dissolve=0.79),
    '승': dict(settle=0.060, fric=0.86, turb=0.22, swirl=0.00, glow=1.00, ghost=0.16, fog=0.04, spread=0.60, dissolve=0.79),
    '전': dict(settle=0.034, fric=0.90, turb=0.45, swirl=0.55, glow=1.55, ghost=0.10, fog=0.04, spread=0.80, dissolve=0.79),
    '결': dict(settle=0.026, fric=0.92, turb=0.30, swirl=0.00, glow=0.70, ghost=0.20, fog=0.35, spread=0.90, dissolve=0.78),
}

# 감정 — 1팀 7종. 값은 1.0 근처에서 얇게 곱한다 (intensity 만큼만 중립에서 밀어낸다)
EMOTIONS = {
    '기쁨': dict(sat=1.12, warm=+0.10, turb=0.90, glow=1.10),
    '슬픔': dict(sat=0.85, warm=-0.10, turb=0.85, glow=0.90),
    '분노': dict(sat=1.12, warm=+0.12, turb=1.20, glow=1.10),
    '공포': dict(sat=0.88, warm=-0.08, turb=1.22, glow=0.92),
    '놀람': dict(sat=1.05, warm=+0.02, turb=1.12, glow=1.15),
    '혐오': dict(sat=0.85, warm=-0.06, turb=0.95, glow=0.88),
    '중립': dict(sat=1.00, warm=0.00, turb=1.00, glow=1.00),
}

# 전(轉) 반전 때 오브제가 바뀌는 색 — 배경 감정 색조(기쁨 금빛 · 슬픔 파랑 · 분노 붉음 · 공포 남보라 · 놀람 자홍 · 혐오 풀빛)의 반대색
REVERSAL_TINT = {
    '기쁨': (0.35, 0.75, 1.00), '슬픔': (1.00, 0.68, 0.30), '분노': (0.30, 0.90, 0.90),
    '공포': (1.00, 0.72, 0.30), '놀람': (0.60, 1.00, 0.40), '혐오': (1.00, 0.42, 0.80), '중립': (1.00, 0.72, 0.30),
}

# ─────────────────────────────────────────────────────────────
# 2. 법칙 → 오브제 동작
#    GROUPS : 오브제 이름에 이 말이 있으면 그 무리. 법칙 문장에 무리의 낱말이 있으면 그 오브제가 주어/대상
#    LAW_RULES : 법칙 문장의 낱말 → 동작
# ─────────────────────────────────────────────────────────────
GROUPS = {
    '서류철': ['서류철', '서류', '책장', '페이지', '표지'],
    '종이': ['종이', '글자', '글씨'],
    '항해일지': ['항해일지', '일지', '마지막 장', '얼룩'],
    '그림자': ['그림자', '형상', '팔이', '팔은'],
    '웅덩이': ['웅덩이', '냉동액'],
    '물방울': ['물방울'],
    '타일': ['타일', '균열', '금이', '금은', '바닥의 금'],
    '손': ['손', '손끝'],
}
LAW_RULES = [
    ('float',      ['떠', '부유', '공중', '닿지 않', '튕겨', '튀어 오', '위로 떨어', '위로 떠', '머무는 시간', '거꾸로 솟', '솟아', '거꾸로 배관']),
    ('glide',      ['미끄러지듯', '미끄러져', '옆으로', '따라가', '따라감', '옮겨']),
    ('weightless', ['무게가 사라', '가벼워', '무게를 잃', '무게가 실리지 않', '무게가 점차 사라']),
    ('heavy',      ['무거워', '무게만 늘', '무게가 늘', '가라앉', '쌓이', '쌓임', '눌어붙']),
    ('rotate',     ['회전', '돌며', '천천히 돈']),
    ('ash',        ['바스러', '재처럼', '부서']),
    ('vanish',     ['사라짐', '사라지', '지워', '없어', '흡수', '삼키', '소멸', '메워']),
    ('stretch',    ['늘어', '길게', '비율', '길어지', '넓게 벌어', '팽창', '번져', '번지']),
    ('flutter',    ['팔락', '넘어가', '넘어감', '떨리', '떨림', '수축', '휘어', '동기화', '박동', '맥박', '숨결']),
    ('crack',      ['균열', '금이', '벌어', '갈라']),
    ('precede',    ['먼저', '앞서', '역전', '닿기도 전', '닿기 전', '늦게 따라', '한 박자 늦게']),
    ('flicker',    ['나타나고 사라', '있다가 없다가', '임의로 변', '깜빡', '다시 앞에 나타', '다시 나타']),
    ('still',      ['변하지 않', '흔들리지 않', '잔물결 하나', '고정되어', '고정됨', '고정된', '그대로 매달려', '그대로 머', '움직이지 않',
                    '멈추고', '멈춰', '멈춘 채', '어긋남 없이']),
    ('recede',     ['멀어', '좁혀지지 않', '작아지', '아득']),
]
# 먼저 보고 지우는 표현 — 이 말 안의 낱말이 다른 동작으로 두 번 잡히지 않게
PRIORITY = ['flicker', 'weightless', 'heavy', 'precede', 'stretch']
BEHAVIOR_KO = {
    'float': '부유', 'glide': '미끄러짐', 'weightless': '무게 잃음', 'heavy': '무거워짐', 'rotate': '회전',
    'ash': '재처럼 바스러짐', 'vanish': '지워짐', 'stretch': '늘어남', 'flutter': '팔락임', 'crack': '갈라짐',
    'precede': '인과 역전(결과가 먼저)', 'flicker': '있다 없다 함', 'still': '미동 없음', 'recede': '멀어짐',
}


import re as _re
_HANGUL = '가-힣'


def _jong_n(ch):
    """마지막 글자 받침이 ㄴ 인지 (꾸밈말 '낡은 · 긴 · 푸른' 거르기)"""
    c = ord(ch) - 0xAC00
    return 0 <= c < 11172 and c % 28 == 4


def name_tokens(name):
    """오브제 이름에서 법칙 문장과 맞춰 볼 낱말을 뽑는다
    '/ ( ) ·' 로 나뉜 각 덩어리의 마지막 낱말(머리 명사)은 늘 넣고, 꾸밈말(받침 ㄴ)은 뺀다"""
    toks = []
    for chunk in _re.split(r'[/()·,\[\]]+', name):
        words = [w for w in chunk.split() if w]
        for i, w in enumerate(words):
            if len(w) >= 3 and w[-1] in '의과와':
                w = w[:-1]
            if i == len(words) - 1 or not _jong_n(w[-1]) or any(c.isdigit() for c in w):
                toks.append(w)
    return list(dict.fromkeys(t for t in toks if t))


def _hit(tok, law):
    if len(tok) >= 2:
        # '바닥에서 떠오름' 처럼 '~에서' 로만 나오면 장소일 뿐 주어가 아니다
        return any(not law.startswith('에서', i + len(tok)) for i in _find_all(tok, law))
    # 한 글자(손 · 막 · 금 · 문 · 종)는 낱말 경계에서만 — '손바닥' 의 '손', '막다' 의 '막' 오인 방지
    return _re.search(rf'(?<![{_HANGUL}]){tok}(?=$|[^{_HANGUL}]|[이가을를은는의에도만과와로])', law) is not None


def _find_all(tok, text):
    i = text.find(tok)
    while i >= 0:
        yield i
        i = text.find(tok, i + 1)


def _says(word, text):
    """문장에 그 낱말이 '긍정으로' 있는지 — '멀어지지 않고' 처럼 바로 뒤에서 부정되면 아니다"""
    i = text.find(word)
    while i >= 0:
        after = text[i + len(word):i + len(word) + 4]  # '멀어지지 않고' · '흩어지지 못해'
        longer = text[i + len(word):i + len(word) + 16]  # '멀어지거나 가까워지지 않고'
        neg = ('않' in after or '못' in after) or _re.match(r'[가-힣]*거나\s*[가-힣]*지\s*(않|못)', longer)
        if '않' in word or not neg:
            return True
        i = text.find(word, i + 1)
    return False


def object_groups(name):
    return [g for g, words in GROUPS.items() if g in name or any(w in name for w in words)]


def analyze_scene(sc):
    """physics_laws 를 오브제별 동작 세기(0~1)로 옮긴다. 옮긴 근거를 log 로 남긴다."""
    objs = sc.get('objects') or []
    groups = [object_groups(o) for o in objs]
    toks = [name_tokens(o) for o in objs]
    beh = [dict() for _ in objs]
    log = []
    for law in sc.get('physics_laws') or []:
        # 무리 낱말 중 한 글자(손)는 낱말 경계에서만 — '손상' 의 '손' 오인 방지
        ghit = [any(any((w in law) if len(w) >= 2 else _hit(w, law) for w in GROUPS[g]) for g in gs) for gs in groups]
        hits = [i for i in range(len(objs)) if ghit[i] or any(_hit(t, law) for t in toks[i])]
        # '바닥 자국' · '손가락 자국' 처럼 흔한 낱말 하나만 겹친 오브제는, 이름이 더 많이 겹친 오브제가 있으면 뺀다
        score = {i: sum(_hit(t, law) for t in toks[i]) for i in hits}
        if hits and max(score.values()) >= 2:
            hits = [i for i in hits if score[i] >= 2 or ghit[i]]
        found, rest = [], law
        for b in PRIORITY + [r for r, _ in LAW_RULES if r not in PRIORITY]:
            words = dict(LAW_RULES)[b]
            hit = [w for w in words if _says(w, rest)]
            if hit:
                found.append(b)
                if b in PRIORITY:  # '무게가 사라지고' 의 '사라' 가 지워짐으로 다시 잡히지 않게
                    for w in hit:
                        rest = rest.replace(w, ' ')
        if not hits:
            reason = '사운드 몫' if '소리' in law else '배경 몫 (오브제가 주어가 아님)'
            log.append({'law': law, 'applied': False, 'reason': reason})
            continue
        if not found:
            log.append({'law': law, 'applied': False, 'objects': [objs[i] for i in hits], 'reason': '옮길 동작 낱말 없음'})
            continue
        applied = {}
        for b in found:
            targets = hits
            if b == 'crack':  # 갈라짐은 타일 무리에만 — 없으면 걸린 오브제 전부
                tile = [i for i in hits if '타일' in groups[i]]
                targets = tile or hits
            if b == 'weightless':
                for i in targets:
                    beh[i]['float'] = min(1.0, beh[i].get('float', 0) + 0.6)
            for i in targets:
                beh[i][b] = min(1.0, beh[i].get(b, 0) + 1.0)
            applied[BEHAVIOR_KO[b]] = [objs[i] for i in targets]
        log.append({'law': law, 'applied': True, 'behaviors': applied})
    return beh, log


# ─────────────────────────────────────────────────────────────
# 3. 도우미
# ─────────────────────────────────────────────────────────────
def smoothstep(a, b, x):
    t = np.clip((x - a) / np.maximum(b - a, 1e-6), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def find_font(size):
    for p in ['C:/Windows/Fonts/malgun.ttf', 'C:/Windows/Fonts/malgunbd.ttf',
              '/System/Library/Fonts/AppleSDGothicNeo.ttc',
              '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
              '/usr/share/fonts/truetype/nanum/NanumGothic.ttf']:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return None


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return 'ffmpeg'


def safe_name(name):
    return _re.sub(r'[\\/:*?"<>|]', '_', name).replace(' ', '_')


def load_objects_index(obj_dir, scene_no, names):
    """output_objects/scene_NN/obj_i_이름.png — 없으면 경고하고 건너뛴다"""
    d = Path(obj_dir) / f'scene_{scene_no:02d}'
    files = []
    for i, n in enumerate(names, 1):
        p = d / f"obj_{i}_{safe_name(n)}.png"
        if not p.exists():
            cand = sorted(d.glob(f'obj_{i}_*.png'))
            p = cand[0] if cand else None
        if p is None:
            print(f'  ! 장면 {scene_no} 오브제 {i} ({n}) PNG 가 없어 건너뜀')
        files.append(p)
    return files


# ─────────────────────────────────────────────────────────────
# 4. 장면 하나 — 입자를 만들고 매 프레임 움직인다
# ─────────────────────────────────────────────────────────────
class Scene:
    def __init__(self, sc, idx, n_scenes, files, W, H, prev_cloud, rng, style='analog', cell=12,
                 emerge='point', reversal=0.6, quiet=False, seed_glow=1.0, dissolve_shift=0.0):
        self.W, self.H = W, H
        self.style, self.cell = style, cell
        digital = style == 'digital'
        # 디지털 — 더 세게 끌리고 덜 미끄러워 제자리를 지나쳤다 돌아온다(통통 튄다) · 블록이 커서 난류도 크게
        self.k_mul, self.fric_off, self.noise_mul = (1.8, -0.08, 1.6) if digital else (1.0, 0.0, 1.0)
        self.sc = sc
        self.act = ACT_NAMES[min(3, idx * 4 // max(1, n_scenes))]
        self.A = ACTS[self.act]
        me = sc.get('main_emotion') or {}
        e = EMOTIONS.get(me.get('label'), EMOTIONS['중립'])
        k = float(me.get('intensity') or 0.0)
        self.emo = {key: 1 + (val - 1) * k if key != 'warm' else val * k for key, val in e.items()}
        self.emo_label = me.get('label') or '중립'
        self.beh, self.law_log = analyze_scene(sc)
        names = sc.get('objects') or []
        keep = [i for i, f in enumerate(files) if f is not None]
        self.names = [names[i] for i in keep]
        beh = [self.beh[i] for i in keep]
        n = len(keep)
        self.n = n

        # 오브제 자리 — 가로로 고르게, 위아래로 살짝 어긋나게
        spacing = min(0.27, 0.80 / max(n, 1))
        box_h = H * (0.42 if n <= 3 else 0.36)
        box_w = W * spacing * 0.95
        anchors, sizes, ghosts = [], [], []
        P_local, P_col, P_alpha, P_obj, P_thr, P_grp, P_birth, P_spawn = [], [], [], [], [], [], [], []
        P_seed = []
        step = max(1, round(2 * H / 1080))
        for j, oi in enumerate(keep):
            img = Image.open(files[oi]).convert('RGBA')
            bb = img.getchannel('A').point(lambda a: 255 if a > 20 else 0).getbbox()
            if bb:
                img = img.crop(bb)
            s = min(box_w / img.width, box_h / img.height)
            dw, dh = max(8, int(img.width * s)), max(8, int(img.height * s))
            img = img.resize((dw, dh), Image.LANCZOS)
            arr = np.asarray(img).astype(np.float32) / 255.0
            ax = W * (0.5 + (j - (n - 1) / 2) * spacing)
            ay = H * (0.53 + (0.035 if j % 2 else -0.035))
            anchors.append((ax, ay))
            sizes.append((dw, dh))
            prem = arr.copy()
            prem[..., :3] *= prem[..., 3:4]
            ghosts.append(prem)

            if digital:
                # 블록 하나 = 입자 하나 — 오브제를 격자 칸으로 줄여 칸마다 평균 색을 뽑는다
                gw, gh = max(2, round(dw / (cell * 0.8))), max(2, round(dh / (cell * 0.8)))  # 칸보다 조금 촘촘히 — 구멍 방지
                small = np.asarray(img.resize((gw, gh), Image.BOX)).astype(np.float32) / 255.0
                ys, xs = np.mgrid[0:gh, 0:gw]
                a = small[ys, xs, 3]
                m = a > 0.45
                xs, ys = xs[m], ys[m]
                col = small[ys, xs, :3] / np.maximum(small[ys, xs, 3:4], 1e-3)
                a = np.ones(len(xs), np.float32)
                lx, ly = (xs + 0.5) * dw / gw - dw / 2, (ys + 0.5) * dh / gh - dh / 2
                gi, gj = xs, ys
            else:
                ys, xs = np.mgrid[0:dh:step, 0:dw:step]
                a = arr[ys, xs, 3]
                m = a > 0.25
                xs, ys, a = xs[m], ys[m], a[m]
                cap = 30000
                if len(xs) > cap:
                    sel = rng.choice(len(xs), cap, replace=False)
                    xs, ys, a = xs[sel], ys[sel], a[sel]
                col = arr[ys, xs, :3]
                gi, gj = xs // step, ys // step
                # 표본 격자가 무늬로 비치지 않게 칸 안에서 살짝 흔든다 (난수 대신 번호로 정해 결과가 매번 같다)
                hsh = np.arange(len(xs), dtype=np.float64)
                jx = (np.modf(np.sin(hsh * 12.9898) * 43758.5453)[0] % 1.0) - 0.5
                jy = (np.modf(np.sin(hsh * 78.233) * 12345.6789)[0] % 1.0) - 0.5
                lx, ly = xs - dw / 2 + jx * step * 0.9, ys - dh / 2 + jy * step * 0.9
            cnt = len(xs)
            # 점 → 성긴 윤곽 → 촘촘한 전체 : 격자 8칸 · 4칸 · 2칸 · 1칸 간격의 입자 순서로 태어난다
            lv = np.full(cnt, 3.0)
            lv[(gi % 2 == 0) & (gj % 2 == 0)] = 2
            lv[(gi % 4 == 0) & (gj % 4 == 0)] = 1
            lv[(gi % 8 == 0) & (gj % 8 == 0)] = 0
            b = beh[j]
            # 풀리는 순서 — 지워짐은 위에서부터(글자부터 지워진다) · 재처럼은 가장자리부터 · 그 밖은 흩어서
            r = np.sqrt((lx / (dw / 2)) ** 2 + (ly / (dh / 2)) ** 2)
            if b.get('vanish'):
                thr = 0.8 * ((ly + dh / 2) / dh) + 0.2 * rng.random(cnt)
            elif b.get('ash'):
                thr = 0.7 * (1 - np.clip(r, 0, 1)) + 0.3 * rng.random(cnt)
            else:
                thr = rng.random(cnt)
            # 태어나는 자리
            #   point : 한 점에서 시작한다 — 앞 장면 잔해 중 이 오브제 자리에 가장 가까운 한 점 (장면 사이가 이어진다)
            #           결과가 먼저(인과 역전)면 그 점이 오브제 위쪽에 있어 아래로 내려앉으며 드러난다
            #   cloud : 예전 방식 — 넓은 구름에서 모인다
            if emerge == 'point':
                if b.get('precede'):
                    seed_pt = np.array([ax, ay - H * 0.30])
                elif prev_cloud is not None and len(prev_cloud):
                    seed_pt = prev_cloud[np.argmin(((prev_cloud - [ax, ay]) ** 2).sum(1))]
                else:
                    seed_pt = np.array([ax, ay])
                sp = seed_pt + rng.normal(0, 1.5 * H / 1080, (cnt, 2))
                P_seed.append(seed_pt)
            elif b.get('precede'):
                sp = np.stack([ax + lx * 1.6 + rng.normal(0, dw * 0.25, cnt),
                               ay - H * (0.15 + 0.55 * rng.random(cnt))], 1)
            elif prev_cloud is not None and len(prev_cloud):
                sp = prev_cloud[rng.integers(0, len(prev_cloud), cnt)] + rng.normal(0, H * 0.03, (cnt, 2))
            else:
                rad = H * 0.55 * self.A['spread']
                ang = rng.random(cnt) * 2 * np.pi
                rr = rad * np.sqrt(rng.random(cnt))
                sp = np.stack([ax + rr * np.cos(ang), ay + rr * np.sin(ang)], 1)
            P_local.append(np.stack([lx, ly], 1)); P_col.append(col); P_alpha.append(a)
            P_obj.append(np.full(cnt, j)); P_thr.append(thr); P_grp.append(np.clip(((ly + dh / 2) / dh * 8).astype(int), 0, 7))  # 가로 띠 8장 — 책장처럼 한 장씩 있다 없다 한다
            P_birth.append((lv + rng.random(cnt)) / 4 if emerge == 'point' else rng.random(cnt)); P_spawn.append(sp)

        # 오브제별 시간표 (장면 안 비율 u)
        #   point : 점에서 시작해 약 16초(0.22)에 걸쳐 드러난다 · 오브제 사이 간격 0.10(7.5초)
        self.emerge = emerge
        if emerge == 'point':
            gap_e = min(0.10, 0.40 / max(n - 1, 1))
            self.enter = np.array([0.015 + gap_e * j for j in range(n)])  # 첫 점은 장면 시작 약 1초 뒤
            self.formed = self.enter + 0.22
        else:
            self.enter = np.array([0.04 + 0.13 * j for j in range(n)])
            self.formed = self.enter + 0.16
        base = self.A['dissolve'] + dissolve_shift
        dis = np.array([min(base + 0.015 * j, 0.86) for j in range(n)])
        pre = np.array([b.get('precede', 0) for b in beh])
        self.dissolve = np.maximum(dis - 0.08 * pre, self.formed + 0.08)  # 결과가 먼저면 조금 일찍 풀린다
        # 전(轉) 반전 — 모였던 형상이 한순간에 터지듯 흩어졌다가, 위아래가 뒤집히고 크기·색이 바뀐 채 다시 모인다
        self.rev = reversal if (reversal is not None and self.act == '전') else None
        if self.rev is not None:
            self.dissolve = np.maximum(self.dissolve, self.rev + 0.10)
        self.rev_fired = False
        # 시작점 빛 — 오브제가 드러나기 전, 그 자리에 은은하게 깜박이는 빛점 (점에서 시작함이 눈에 보이게)
        self.seed_glow_k = seed_glow if emerge == 'point' else 0.0
        self.seed_pts = np.array(P_seed, np.float32) if len(P_seed) == n else None
        self.beh_arr = {k2: np.array([b.get(k2, 0.0) for b in beh]) for k2, _ in LAW_RULES}
        self.anchors = np.array(anchors, np.float32)
        self.sizes = np.array(sizes, np.float32)
        self.ghosts = ghosts
        self.phase = rng.random(n) * 2 * np.pi
        self.crack_ang = rng.uniform(-0.5, 0.5, n)

        self.local = np.concatenate(P_local).astype(np.float32)
        col = np.concatenate(P_col)
        # 원래 색에서 밝기·채도를 먼저 잰다 (감정 색을 입힌 뒤에 재면 밤색이 무채색으로 오판된다)
        lum = col @ np.array([0.299, 0.587, 0.114])
        chroma = col.max(1) - col.min(1)
        # 감정 색 — 채도·난색 (얇게)
        g = col.mean(1, keepdims=True)
        col = g + (col - g) * self.emo['sat']
        col[:, 0] += self.emo['warm'] * 0.3
        col[:, 2] -= self.emo['warm'] * 0.3
        # 어두운 무채색(검은 그림자 등)은 어두운 배경에 묻히지 않게 차가운 테두리 빛을 얹고,
        # 어두운 유채색(밤색 표지 등)은 색을 지킨 채 밝기만 올린다
        vmax = np.concatenate(P_col).max(1)
        sat_hsv = chroma / np.maximum(vmax, 1e-3)
        achrom = (sat_hsv < 0.18) | (vmax < 0.06)
        lift = np.clip(0.30 - lum, 0, None) * achrom
        col += lift[:, None] * np.array([0.55, 0.70, 1.00])
        dark_col = (lum < 0.30) & ~achrom
        col[dark_col] *= ((0.30 / np.maximum(lum[dark_col], 0.03)) ** 0.7)[:, None]
        if digital:
            # 원초적 — 채도를 올리고 색을 5단계로 눌러 면을 평평하게 칠한다
            g = col.mean(1, keepdims=True)
            col = posterize_hsv(np.clip(g + (col - g) * 1.3, 0, 1))
        self.col = np.clip(col, 0, 1).astype(np.float32)
        oid = np.concatenate(P_obj)
        sc_col = []
        for j in range(n):
            m = self.col[oid == j].mean(0) if (oid == j).any() else np.ones(3, np.float32)
            m = 0.55 * m + 0.45  # 오브제 색을 띤 밝은 빛
            sc_col.append(m / max(float(m @ np.array([0.299, 0.587, 0.114])), 1e-3) * 0.95)
        self.seed_col = np.clip(np.array(sc_col, np.float32), 0, 1)
        tint = np.array(REVERSAL_TINT.get(self.emo_label, REVERSAL_TINT['중립']), np.float32)
        self.rev_tint = tint
        lum2 = self.col @ np.array([0.299, 0.587, 0.114], np.float32)
        rcol = np.clip(np.maximum(lum2, 0.25)[:, None] * tint * 1.25 + 0.12 * self.col, 0, 1)
        self.rev_col = (posterize_hsv(rcol) if digital else rcol).astype(np.float32)
        self.alpha = np.concatenate(P_alpha).astype(np.float32)
        self.obj = np.concatenate(P_obj)
        self.thr = np.concatenate(P_thr).astype(np.float32)
        self.grp = np.concatenate(P_grp)
        stagger = np.where(np.array([b.get('precede', 0) for b in beh])[self.obj] > 0, 0.14, 0.06)
        if emerge == 'point':
            stagger = np.full(len(self.obj), 0.16)  # 태어나는 데 12초 — 점이 먼저, 촘촘한 입자가 나중
        self.birth = self.enter[self.obj] + stagger * np.concatenate(P_birth)  # 결과가 먼저면 비처럼 오래 내려앉는다
        self.pos = np.concatenate(P_spawn).astype(np.float32)
        self.vel = np.zeros_like(self.pos)
        self.released = np.zeros(len(self.pos), bool)
        if not quiet:
            rv = f' · 반전 {self.rev:.2f}' if self.rev is not None else ''
            print(f'  장면 {sc.get("scene")} · {self.act} · {self.emo_label} · 오브제 {n}개 · 입자 {len(self.pos):,}{rv}')

    def rev_phase(self, u):
        """반전 진행 — (뒤집힘 0/1, 끌림 배율, 색 섞임)"""
        if self.rev is None or u < self.rev:
            return 0.0, 1.0, 0.0
        # 약 1초 흩어졌다가 3초 안에 다시 모인다 — 다시 모일 때는 평소보다 2배 세게 끌어 형태를 빨리 세운다
        pull = float(smoothstep(self.rev + 0.012, self.rev + 0.05, u)) * (1 + float(smoothstep(self.rev + 0.012, self.rev + 0.03, u)) * (1 - float(smoothstep(self.rev + 0.08, self.rev + 0.12, u))))
        return 1.0, pull, float(smoothstep(self.rev, self.rev + 0.03, u))

    # 오브제 하나의 '지금 모양' — 동작 세기 × 시간
    def transforms(self, u, t):
        H, W, B = self.H, self.W, self.beh_arr
        F = smoothstep(self.enter, self.formed, u)
        hold = smoothstep(self.formed, self.dissolve, u)
        dy = -B['float'] * (0.06 * H * F + 0.012 * H * np.sin(2 * np.pi * t / 6.5 + self.phase))
        dy -= B['weightless'] * 0.05 * H * hold
        dy += B['heavy'] * 0.04 * H * hold
        dx = B['glide'] * 0.08 * W * np.sin(2 * np.pi * t / 22 + self.phase)
        ang = B['rotate'] * 2 * np.pi * t / 10
        sx = np.cos(ang)
        sx = np.where(np.abs(sx) < 0.12, np.sign(sx + 1e-9) * 0.12, sx)
        sx = np.where(B['rotate'] > 0, sx, 1.0)
        tilt = B['rotate'] * 0.25 * np.sin(t / 4 + self.phase)
        scale = 1 - B['recede'] * 0.4 * u
        stretch = B['stretch'] * (0.7 * hold + 0.05 * np.sin(t / 3 + self.phase))
        c0 = np.where(B['precede'] > 0, self.enter, self.formed)
        steps = 4 * smoothstep(c0, self.dissolve, u)
        stair = np.floor(steps) + smoothstep(0.0, 0.25, steps - np.floor(steps))  # 한 뼘씩 벌어진다
        gap = B['crack'] * 0.012 * H * stair
        burst = np.maximum(0, np.sin(2 * np.pi * t / 4.5 + self.phase)) ** 3
        flut = B['flutter'] * 0.035 * H * burst
        flip, _, _ = self.rev_phase(u)
        if flip:
            tilt = tilt + np.pi  # 위아래가 뒤집힌 채 다시 모인다
            scale = scale * 1.15
        return F, dx, dy, sx, tilt, scale, stretch, gap, flut

    def step(self, u, t):
        self.u_now, self.t_now = u, t
        A, emo = self.A, self.emo
        F, dx, dy, sx, tilt, scale, stretch, gap, flut = self.transforms(u, t)
        o = self.obj
        half = self.sizes / 2
        lx, ly = self.local[:, 0].copy(), self.local[:, 1].copy()
        # 늘어남 — 아래로 갈수록 더 (팔이 바닥까지 늘어진다)
        ly = np.where(ly > 0, ly * (1 + stretch[o]), ly * (1 + 0.15 * stretch[o]))
        # 팔락임 — 가장자리일수록 크게 물결친다
        lx = lx + flut[o] * np.sin(ly / half[o, 1] * np.pi * 1.5 + 6 * t) * np.abs(lx) / half[o, 0]
        # 갈라짐 — 비스듬한 선을 사이에 두고 두 쪽이 벌어진다
        nx, ny = np.cos(self.crack_ang)[o], np.sin(self.crack_ang)[o]
        side = np.sign(lx * nx + ly * ny + 1e-6)
        lx = lx + side * nx * gap[o] / 2
        ly = ly + side * ny * gap[o] / 2
        # 회전(뒤집힘) · 기울기 · 멀어짐
        lx = lx * sx[o] * scale[o]
        ly = ly * scale[o]
        ct, st = np.cos(tilt)[o], np.sin(tilt)[o]
        hx = self.anchors[o, 0] + dx[o] + lx * ct - ly * st
        hy = self.anchors[o, 1] + dy[o] + lx * st + ly * ct
        home = np.stack([hx, hy], 1)

        born = u >= self.birth
        rel_u = self.dissolve[o] + RELEASE_SPAN * self.thr
        self.released |= u >= rel_u
        Fi = F[o]
        still = self.beh_arr['still'][o]
        k = A['settle'] * Fi * (1 + 0.5 * still) * self.k_mul
        k = np.where(self.released, 0.0, k)
        flip, pull, cmix = self.rev_phase(u)
        if flip and not self.rev_fired:  # 반전 순간 — 모든 입자를 바깥으로 한 번에 터뜨린다
            self.rev_fired = True
            live = born & ~self.released
            d = self.pos - self.anchors[o]
            d = d / (np.linalg.norm(d, axis=1, keepdims=True) + 1.0)
            spd = self.H * 0.022 * (0.6 + 0.8 * self.thr)
            self.vel[live] += d[live] * spd[live, None]
        k = k * pull
        # 난류 — 위치마다 세기·방향이 다른 결 (형태가 서기 전일수록 거세다)
        p = self.pos
        T = t * 0.8
        nxf = np.sin(p[:, 1] * 0.011 + T * 0.7 + 1.3) + 0.5 * np.sin(p[:, 0] * 0.023 - T * 1.1 + 0.4)
        nyf = np.cos(p[:, 0] * 0.013 + T * 0.9 + 2.1) + 0.5 * np.cos(p[:, 1] * 0.019 + T * 0.6 + 0.7)
        noise = np.stack([nxf, nyf], 1).astype(np.float32)
        turb = A['turb'] * emo['turb'] * (1 - 0.9 * still) * (0.35 + 0.65 * (1 - Fi))
        acc = (home - p) * k[:, None] + noise * (0.55 * self.noise_mul * turb)[:, None]
        if A['swirl'] > 0:
            rv = p - self.anchors[o]
            r = np.linalg.norm(rv, axis=1, keepdims=True) + 1.0
            tang = np.stack([-rv[:, 1], rv[:, 0]], 1) / r
            acc += tang * (A['swirl'] * 0.35) * (~self.released)[:, None]
        # 풀린 입자 — 재처럼은 위로 날리고 · 지워짐은 제자리에서 꺼지고 · 그 밖은 안개처럼 번진다
        ash, van = self.beh_arr['ash'][o], self.beh_arr['vanish'][o]
        rel = self.released
        up = np.where(ash > 0, -0.06, -0.012)
        acc[rel, 1] += up[rel]
        acc[rel] += noise[rel] * np.where(van[rel] > 0, 0.15, np.where(ash[rel] > 0, 0.9, 0.5))[:, None]
        fric = np.where(rel, 0.96, A['fric'] + 0.06 * still + self.fric_off).astype(np.float32)
        acc[~born] = 0
        self.vel = self.vel * fric[:, None] + acc
        self.vel[~born] = 0
        self.pos = (p + self.vel).astype(np.float32)

        # 보이는 정도
        v = self.alpha * smoothstep(0, 0.03, u - self.birth)
        if self.emerge == 'point':  # 막 태어난 성긴 입자는 더 밝게 — 형태가 서기 전에도 무엇이 자라고 있는지 보이게
            v = v * (1 + 1.2 * (1 - F[o]))
        v = v * (1 - smoothstep(rel_u, rel_u + 0.05, u))
        fl = self.beh_arr['flicker'][o]
        if fl.any():  # 있다 없다 — 무리마다 1.4초에 한 번씩 켜지고 꺼진다 (페이지 수가 변한다)
            tick = int(t / 1.4)
            on = ((self.grp * 2654435761 + tick * 40503 + o * 97) % 7) > 2
            v = v * (1 - fl * (~on) * 0.85)
        if self.style == 'digital':
            v = np.round(v * 2) / 2  # 디지털 — 서서히 꺼지지 않고 켜짐·반·꺼짐 세 단계로 깜박인다
        ash_col = np.where((ash > 0) & rel, 1, 0)[:, None]
        base_col = self.col if cmix == 0 else self.col * (1 - cmix) + self.rev_col * cmix
        col = base_col * (1 - 0.6 * ash_col) + 0.55 * ash_col * np.array([0.75, 0.72, 0.70], np.float32)
        return v.astype(np.float32), col.astype(np.float32), F, dx, dy, sx, tilt, scale, gap

    def seed_lights(self, u, t):
        """시작점 빛 — (위치, 세기, 색). 오브제가 태어나기 1.5초 전부터 깜박이다가 형태가 서면서 사라진다"""
        if self.seed_pts is None or self.seed_glow_k <= 0:
            return None
        on = smoothstep(self.enter - 0.02, self.enter, u) * (1 - smoothstep(self.enter + 0.10, self.enter + 0.20, u))
        pulse = 0.75 + 0.25 * np.sin(2 * np.pi * t / 1.6 + self.phase)
        k = on * pulse * self.seed_glow_k
        if not (k > 0.01).any():
            return None
        return self.seed_pts, k, self.seed_col

    def ghost_layer(self, u, F, dx, dy, sx, tilt, scale, gap, canvas_rgb, canvas_a):
        """원본 PNG 를 아주 옅게 — 입자가 흩어져도 무엇인지 읽히도록 윤곽을 받친다"""
        W, H = self.W, self.H
        D = smoothstep(self.dissolve, self.dissolve + 0.10, u)
        GF = F ** 3 if self.emerge == 'point' else F
        flip, pull, _ = self.rev_phase(u)
        rev_k = pull if flip else 1.0
        for j in range(self.n):
            g = self.A['ghost'] * GF[j] * rev_k * (1 - D[j]) * (1 + 0.8 * self.beh_arr['still'][j]) * (1 - 0.6 * min(1, gap[j] / (0.05 * H + 1e-6)))
            if g < 0.004:
                continue
            img = self.ghosts[j]
            h, w = img.shape[:2]
            a, b_ = sx[j] * scale[j], scale[j]
            c, s = math.cos(tilt[j]), math.sin(tilt[j])
            M = np.array([[a * c, -b_ * s, 0], [a * s, b_ * c, 0]], np.float32)
            M[:, 2] = np.array([self.anchors[j, 0] + dx[j], self.anchors[j, 1] + dy[j]]) - M[:, :2] @ np.array([w / 2, h / 2])
            corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], np.float32) @ M[:, :2].T + M[:, 2]
            x0, y0 = np.floor(corners.min(0)).astype(int)
            x1, y1 = np.ceil(corners.max(0)).astype(int)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            M2 = M.copy(); M2[:, 2] -= [x0, y0]
            roi = cv2.warpAffine(img, M2, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderValue=0)
            rgb = roi[..., :3]
            if flip:  # 반전 뒤에는 원본 윤곽도 반대색으로 — 흰 원본이 비쳐 하얗게 번지지 않게
                rgb = (rgb @ LUMW)[..., None] * self.rev_tint * 1.25
            canvas_rgb[y0:y1, x0:x1] += rgb * g
            canvas_a[y0:y1, x0:x1] += roi[..., 3] * g

    def cloud(self):
        return self.pos.copy()


# ─────────────────────────────────────────────────────────────
# 5. 배경 — 오브제만일 때는 어두운 바탕, 통합일 때는 배경 영상
# ─────────────────────────────────────────────────────────────
class Background:
    def __init__(self, W, H, path=None, json_path=None, n_scenes=4, scene_sec=75.0):
        self.W, self.H = W, H
        self.cap = None
        if path:
            self.cap = cv2.VideoCapture(str(path))
            if not self.cap.isOpened():
                sys.exit(f'배경 영상을 열 수 없습니다: {path}')
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 60
            self.total = self.cap.get(cv2.CAP_PROP_FRAME_COUNT) / self.fps
            starts = None
            if json_path and Path(json_path).exists():
                vj = json.load(open(json_path, encoding='utf-8'))
                starts = [float(s.get('start_sec', 0)) for s in vj.get('scenes', [])]
            if not starts or len(starts) < n_scenes:
                starts = [self.total * k / n_scenes for k in range(n_scenes)]
            self.starts = starts[:n_scenes] + [self.total]
            self.idx = -1
            self.frame = None
            print(f'  배경 영상 {path} · {self.total:.1f}초 · {self.fps:.0f}fps · 장면 시작 {[round(s, 1) for s in self.starts[:-1]]}')
        else:
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            r = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.52) / H) ** 2)
            k = np.clip(1 - r * 1.6, 0, 1)[..., None]
            self.dark = (np.array([0.016, 0.016, 0.026]) * (1 - k) + np.array([0.060, 0.064, 0.090]) * k).astype(np.float32)
        self.scene_sec = scene_sec

    def get(self, scene_i, tau):
        if self.cap is None:
            return self.dark.copy()
        a, b = self.starts[scene_i], self.starts[scene_i + 1]
        bt = a + (b - a) * min(tau / self.scene_sec, 0.9999)
        j = int(bt * self.fps)
        if j < self.idx or j > self.idx + 240:  # 뒤로 가거나 많이 건너뛸 때만 탐색
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, j)
            self.idx = j - 1
        while self.idx < j:
            ok = self.cap.grab()
            if not ok:
                break
            self.idx += 1
            if self.idx == j:
                ok, fr = self.cap.retrieve()
                if ok:
                    fr = cv2.resize(fr, (self.W, self.H), interpolation=cv2.INTER_AREA)
                    self.frame = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        if self.frame is None:
            return np.zeros((self.H, self.W, 3), np.float32)
        return self.frame.copy()


# ─────────────────────────────────────────────────────────────
# 6. 그리기
# ─────────────────────────────────────────────────────────────
def splat(pos, v, col, W, H):
    x = np.round(pos[:, 0]).astype(np.int64)
    y = np.round(pos[:, 1]).astype(np.int64)
    m = (v > 0.003) & (x >= 0) & (x < W) & (y >= 0) & (y < H)
    idx = y[m] * W + x[m]
    w = v[m]
    out = np.empty((H, W, 4), np.float32)
    out[..., 3] = np.bincount(idx, weights=w, minlength=W * H).reshape(H, W)
    for c in range(3):
        out[..., c] = np.bincount(idx, weights=w * col[m, c], minlength=W * H).reshape(H, W)
    return out


def posterize_hsv(rgb):
    """색을 몇 단계로 누른다 — 색상 15° · 채도 4단계 · 밝기 6단계 (밤색이 회색으로 뭉개지지 않게 색상은 지킨다)"""
    shp = rgb.shape
    hsv = cv2.cvtColor(np.clip(rgb, 0, 1).reshape(-1, 1, 3).astype(np.float32), cv2.COLOR_RGB2HSV)
    hsv[..., 0] = (np.round(hsv[..., 0] / 15) * 15) % 360
    hsv[..., 1] = np.round(hsv[..., 1] * 3) / 3
    hsv[..., 2] = np.round(hsv[..., 2] * 5) / 5
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).reshape(shp)


def render_digital(pos, v, col, W, H, cell):
    """디지털 — 입자를 화면 격자 칸에 떨어뜨려 칸마다 하나의 평평한 색 블록으로 칠한다"""
    Wg, Hg = -(-W // cell), -(-H // cell)
    gx = np.floor(pos[:, 0] / cell).astype(np.int64)
    gy = np.floor(pos[:, 1] / cell).astype(np.int64)
    m = (v > 0.01) & (gx >= 0) & (gx < Wg) & (gy >= 0) & (gy < Hg)
    idx = gy[m] * Wg + gx[m]
    w = v[m]
    ws = np.bincount(idx, weights=w, minlength=Wg * Hg)
    c = np.stack([np.bincount(idx, weights=w * col[m, k], minlength=Wg * Hg) for k in range(3)], 1) / (ws[:, None] + 1e-6)
    a = 1 - np.exp(-ws * 2.0)
    a = np.where(a > 0.55, 1.0, np.where(a > 0.2, 0.5, 0.0))
    c = posterize_hsv(c)
    up = lambda x: np.repeat(np.repeat(x.reshape(Hg, Wg, -1), cell, 0), cell, 1)[:H, :W]
    return up(c).astype(np.float32), up(a)[..., 0].astype(np.float32)


LUMW = np.array([0.299, 0.587, 0.114], np.float32)


def contrast_prepare(bg, objA, strength, H, W):
    """밝거나 색이 짙은 배경 위에서도 오브제가 드러나게 — 배경 쪽 손질
    오브제 둘레에 부드러운 어두운 받침을 깐다. 받침은 배경이 밝은 자리일수록 짙고, 어두운 자리에서는 거의 없다.
    돌려주는 것: 손질된 배경 · 오브제 자리의 배경 밝기(흐림) · 번짐 빛 배율"""
    qw, qh = max(8, W // 4), max(8, H // 4)
    # 흩어진 입자·옅은 연기 자국은 빼고 촘촘한 몸통에만 받침을 깐다 (받침이 옅은 연기를 드러내 하얀 테두리처럼 보이지 않게)
    occ = cv2.resize(smoothstep(0.25, 0.65, objA).astype(np.float32), (qw, qh), interpolation=cv2.INTER_AREA)
    halo = np.clip(cv2.GaussianBlur(occ, (0, 0), 4.0 * H / 1080 + 1.0) * 2.4, 0, 1)
    lb = cv2.GaussianBlur(cv2.resize(bg, (qw, qh), interpolation=cv2.INTER_AREA) @ LUMW, (0, 0), 3.0 * H / 1080 + 0.5)
    shade = strength * 0.78 * halo * smoothstep(0.12, 0.55, lb)
    bg = bg * (1 - cv2.resize(shade, (W, H), interpolation=cv2.INTER_LINEAR)[..., None])
    lb_after = cv2.resize(lb * (1 - shade), (W, H), interpolation=cv2.INTER_LINEAR)
    glow_k = 1 - 0.75 * smoothstep(0.30, 0.75, lb_after)
    return bg, lb_after, glow_k


def contrast_object(objC, objA, lb, strength, min_gap=0.30):
    """오브제 쪽 손질 — 오브제 밝기가 바로 뒤 배경 밝기와 min_gap 이상 벌어지게 (색은 지킨 채 밝기만)
    입자가 촘촘히 모인 몸통에만 건다 — 흩어진 입자까지 밝히면 오브제 둘레가 하얗게 번진다"""
    lo = objC @ LUMW
    target = np.where(lb < 0.5, np.maximum(lo, lb + min_gap), np.minimum(lo, lb - min_gap))
    ratio = np.clip(target / np.maximum(lo, 0.03), 0.35, 2.6)
    ratio = 1 + (ratio - 1) * strength * smoothstep(0.35, 0.75, objA)
    return np.clip(objC * ratio[..., None], 0, 1)


_SPRITES = {}


def _sprite(H, digital=False, cell=12):
    key = (H, digital, cell)
    if key not in _SPRITES:
        if digital:  # 디지털 — 가운데 한 칸이 가장 밝은 3×3 블록 점
            k = np.array([[0.25, 0.55, 0.25], [0.55, 1.0, 0.55], [0.25, 0.55, 0.25]], np.float32)
            _SPRITES[key] = np.kron(k, np.ones((cell, cell), np.float32))
        else:  # 아날로그 — 작은 심 + 넓은 번짐
            r = int(40 * H / 1080) + 4
            yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
            d2 = xx ** 2 + yy ** 2
            sc, sh = 3.5 * H / 1080 + 0.8, 16 * H / 1080 + 2
            _SPRITES[key] = np.exp(-d2 / (2 * sc ** 2)) * 1.1 + np.exp(-d2 / (2 * sh ** 2)) * 0.55
    return _SPRITES[key]


def draw_seed_lights(frame, lights, H, W, digital=False, cell=12):
    if lights is None:
        return frame
    pts, ks, cols = lights
    sp = _sprite(H, digital, cell)
    h, w = sp.shape
    for (x, y), k, c in zip(pts, ks, cols):
        if k <= 0.01:
            continue
        if digital:
            x, y = (int(x // cell) - 1) * cell, (int(y // cell) - 1) * cell
        else:
            x, y = int(round(x)) - w // 2, int(round(y)) - h // 2
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        patch = sp[y0 - y:y1 - y, x0 - x:x1 - x][..., None] * (c * k)
        frame[y0:y1, x0:x1] = frame[y0:y1, x0:x1] + patch
    return frame


def compose_analog(S, frame, out, u, composite, contrast, fog_col):
    v, col, F, dx, dy, sx, tilt, scale, gap = out
    W, H = S.W, S.H
    acc = splat(S.pos, v, col, W, H)
    acc = cv2.GaussianBlur(acc, (0, 0), 0.7 * H / 1080 + 0.3)
    aw = acc[..., 3]
    objA = 1 - np.exp(-aw * 1.6)
    objC = acc[..., :3] / (aw[..., None] + 1e-6)
    small = cv2.resize(acc[..., :3], (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    glow = cv2.resize(cv2.GaussianBlur(small, (0, 0), 6 * H / 1080 + 1), (W, H), interpolation=cv2.INTER_LINEAR)
    gr = np.zeros((H, W, 3), np.float32); ga = np.zeros((H, W), np.float32)
    S.ghost_layer(u, F, dx, dy, sx, tilt, scale, gap, gr, ga)
    glow_k = 1.0
    if contrast > 0:
        frame, lb, glow_k = contrast_prepare(frame, np.clip(objA + ga, 0, 1), contrast, H, W)
        objC = contrast_object(objC, objA, lb, contrast)
        glow_k = glow_k[..., None]
    frame = frame * (1 - np.clip(ga, 0, 1)[..., None]) + gr
    frame = frame * (1 - objA[..., None]) + objC * objA[..., None]
    frame += glow * (0.35 * S.A['glow'] * S.emo['glow']) * glow_k
    frame = draw_seed_lights(frame, S.seed_lights(u, S.t_now), H, W)
    if not composite:
        frame = frame * (1 - S.A['fog'] * 0.25) + fog_col * (S.A['fog'] * 0.25)
    return frame


def compose_digital(S, frame, out, contrast, cell, gap_mask):
    v, col = out[0], out[1]
    W, H = S.W, S.H
    objC, objA = render_digital(S.pos, v, col, W, H, cell)
    if contrast > 0:
        frame, lb, _ = contrast_prepare(frame, objA, contrast, H, W)
        objC = contrast_object(objC, objA, lb, contrast)
    frame = frame * (1 - objA[..., None]) + objC * gap_mask * objA[..., None]
    return draw_seed_lights(frame, S.seed_lights(S.u_now, S.t_now), H, W, True, cell)


# ─────────────────────────────────────────────────────────────
# 7. 선화(line) 스타일 — 오브제를 굵은 손그림 선의 기하 도형으로 다시 그린다 (교수님 예제 영상 방향)
#    오브제 PNG 의 윤곽 → 다각형·원으로 단순화 + 안쪽 큰 선 몇 개 → 색 선 몇 획
#    물리 법칙 → 덧그림 기호 (부유 = 물결 · 회전 = 나선 · 갈라짐 = 지그재그 · 바스러짐 = 흩어진 짧은 선 …)
#    획이 하나씩 그려졌다가(점에서 시작) 지워지며, 장면의 오브제 조각이 작게 메아리처럼 떠다닌다
#    기승전결에 따라 크기가 커졌다가(전 = 절정) 다시 작아진다
# ─────────────────────────────────────────────────────────────
LINE_PAL = {'주황': (255, 140, 40), '초록': (80, 220, 120), '하늘': (70, 190, 255), '분홍': (255, 90, 170),
            '노랑': (255, 220, 60), '보라': (170, 110, 255), '흰': (240, 240, 240), '빨강': (255, 80, 80)}
LINE_EMO_ORDER = {  # 흰색은 맨 뒤 — 예제처럼 선명한 색이 대부분이 되게
    '공포': ['하늘', '보라', '빨강', '초록', '분홍', '노랑', '주황', '흰'],
    '기쁨': ['노랑', '주황', '분홍', '초록', '하늘', '보라', '빨강', '흰'],
    '슬픔': ['하늘', '보라', '초록', '분홍', '노랑', '주황', '빨강', '흰'],
    '분노': ['빨강', '주황', '노랑', '분홍', '보라', '하늘', '초록', '흰'],
    '놀람': ['분홍', '노랑', '초록', '하늘', '주황', '보라', '빨강', '흰'],
    '혐오': ['초록', '보라', '노랑', '하늘', '분홍', '주황', '빨강', '흰'],
    '중립': ['주황', '초록', '하늘', '분홍', '노랑', '보라', '빨강', '흰'],
}
# 크기 변화 (10/15 피드백 "작았다 커졌다") — 장면 안에서도 오브제 크기가 계속 바뀐다
#   숨쉬기: 6~11초 주기로 천천히 커졌다 작아짐 (폭) · 부풀기: 18~30초마다 4~6초 동안 크게 부풀었다 돌아옴 (폭)
#   법칙 흐름: 늘어남 → 점점 커짐 · 무거워짐 → 점점 작아짐 · 부유/무게 잃음 → 조금 커짐 · 멀어짐 → 점점 작아짐(기존)
#   전(轉): 반전 6초 전부터 부풀어 오르다 터진다
SIZE_BREATH = {'기': 0.10, '승': 0.14, '전': 0.20, '결': 0.10}
SIZE_SWELL = {'기': 0.25, '승': 0.35, '전': 0.55, '결': 0.25}
SIZE_TREND = {'stretch': 0.35, 'heavy': -0.25, 'float': 0.10, 'weightless': 0.15}

LINE_ACT = {  # 크기 배율 · 메아리(초당 개수 · 크기 범위) · 선 굵기 배율
    # 예제 영상처럼 '작게 시작해서 절정에 크게 터진다' — 기·승은 작게, 전은 화면을 덮을 만큼, 결은 다시 작게
    '기': dict(scale=0.45, echo_rate=0.90, echo_size=(0.04, 0.12), thick=0.75),
    '승': dict(scale=0.65, echo_rate=1.10, echo_size=(0.08, 0.22), thick=0.9),
    '전': dict(scale=1.60, echo_rate=2.20, echo_size=(0.35, 1.20), thick=1.7),
    '결': dict(scale=0.55, echo_rate=0.60, echo_size=(0.05, 0.15), thick=0.8),
}


def _densify(pts, step=0.03):
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(np.hypot(*(b - a)) / step))
        for s in np.linspace(0, 1, n + 1)[1:]:
            out.append(a + (b - a) * s)
    return np.array(out, np.float32)


def extract_glyph(path, max_lines=3):
    """오브제 PNG → 단위 상자([-0.5, 0.5]) 안의 획 목록 [(점들, 굵기 배율, 무리)]"""
    im = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim < 3 or im.shape[2] < 4:
        return [], (200, 200, 200)
    a = im[..., 3]
    ys, xs = np.where(a > 40)
    if len(xs) == 0:
        return [], (200, 200, 200)
    # 떨어진 작은 조각은 크기 계산에서 뺀다 (가장 큰 덩어리 기준)
    mask = (a > 100).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)
    if not cnts:
        return [], (200, 200, 200)
    big = [c for c in cnts if cv2.contourArea(c) > 0.04 * cv2.contourArea(cnts[0])]
    x0, y0, bw, bh = cv2.boundingRect(np.vstack(big))
    S = max(bw, bh)
    cx, cy = x0 + bw / 2, y0 + bh / 2
    norm = lambda p: np.stack([(p[:, 0] - cx) / S, (p[:, 1] - cy) / S], 1).astype(np.float32)
    rgb = im[..., 2::-1][a > 100].mean(0)
    strokes = []
    for k, c in enumerate(big[:3]):
        A = cv2.contourArea(c)
        P = cv2.arcLength(c, True)
        circ = 4 * np.pi * A / (P * P + 1e-6)
        if circ > 0.78:  # 둥근 덩어리는 원으로
            (ex, ey), r = cv2.minEnclosingCircle(c)
            t = np.linspace(0, 2 * np.pi, 40)
            pts = np.stack([ex + r * 0.95 * np.cos(t), ey + r * 0.95 * np.sin(t)], 1)
        else:  # 그 밖은 꼭짓점 몇 개짜리 다각형으로
            ap = cv2.approxPolyDP(c, 0.03 * P, True).reshape(-1, 2).astype(np.float32)
            pts = np.vstack([ap, ap[:1]])
        strokes.append((norm(pts), 1.0 if k == 0 else 0.8, 'body'))
    g = cv2.cvtColor(im[..., :3], cv2.COLOR_BGR2GRAY)
    g[a < 100] = 0
    ed = cv2.Canny(g, 40, 120)
    ed[cv2.erode(mask, np.ones((9, 9), np.uint8)) == 0] = 0
    L = cv2.HoughLinesP(ed, 1, np.pi / 180, 40, minLineLength=int(0.18 * S), maxLineGap=int(0.04 * S))
    if L is not None:  # 안쪽의 큰 선 몇 개
        # OpenCV 버전에 따라 (N, 1, 4) 또는 (N, 4) 로 돌려준다 — 어느 쪽이든 (N, 4) 로 맞춘다
        L = sorted(np.asarray(L).reshape(-1, 4), key=lambda l: -np.hypot(l[2] - l[0], l[3] - l[1]))
        used = []
        for l in L:
            mid = ((l[0] + l[2]) / 2, (l[1] + l[3]) / 2)
            if any(np.hypot(mid[0] - u[0], mid[1] - u[1]) < 0.15 * S for u in used):
                continue
            used.append(mid)
            strokes.append((norm(np.array([[l[0], l[1]], [l[2], l[3]]], np.float32)), 0.7, 'inner'))
            if len(used) >= max_lines:
                break
    return strokes, tuple(int(v) for v in rgb)


def law_marks(beh):
    """물리 법칙 → 덧그림 기호 (단위 상자 기준 좌표)"""
    out = []
    x = np.linspace(-0.45, 0.45, 40)
    if beh.get('float') or beh.get('weightless'):
        out.append(np.stack([x, 0.64 + 0.05 * np.sin(x * 4 * np.pi)], 1))  # 아래 물결
    if beh.get('glide'):
        for yy in (0.05, 0.22):
            out.append(np.array([[-0.95, yy], [-0.62, yy]], np.float32))
    if beh.get('rotate'):
        t = np.linspace(0, 1.7 * np.pi, 50)
        r = 0.56 + 0.10 * t / (1.7 * np.pi)
        out.append(np.stack([r * np.cos(t - 2.2), r * np.sin(t - 2.2)], 1))  # 둘레 나선
    if beh.get('ash'):
        for k in range(7):
            ang = k * 0.9 + 0.4
            p = np.array([np.cos(ang), np.sin(ang)]) * (0.62 + 0.07 * (k % 3))
            out.append(np.array([p, p + np.array([np.cos(ang + 0.6), np.sin(ang + 0.6)]) * 0.06], np.float32))
    if beh.get('stretch'):
        for xx in (-0.28, 0.22):
            out.append(np.array([[xx, 0.35], [xx + 0.03, 0.62], [xx - 0.02, 0.92]], np.float32))
    if beh.get('flutter'):
        yy = np.linspace(-0.4, 0.4, 9)
        out.append(np.stack([0.62 + 0.06 * (np.arange(9) % 2 * 2 - 1), yy], 1))  # 옆 지그재그
    if beh.get('crack'):
        t = np.linspace(0, 1, 9)
        out.append(np.stack([-0.42 + 0.84 * t + 0.07 * (np.arange(9) % 2 * 2 - 1), -0.45 + 0.9 * t], 1))
    return [np.asarray(m, np.float32) for m in out]


def _wobble(pts, amp, seed, t):
    i = np.arange(len(pts), dtype=np.float32)
    off = np.stack([np.sin(i * 0.7 + seed + t * 2.1) + 0.5 * np.sin(i * 1.9 + seed * 2),
                    np.cos(i * 0.6 + seed * 1.3 + t * 1.7) + 0.5 * np.cos(i * 2.3 + seed)], 1)
    return pts + off * amp


# 어린아이 로봇이 그리는 과정 — 획마다 '펜을 대고 망설이다 → 그리다 멈추고 → 틀리면 지우고 → 다시 그린다'
#   획을 그리는 속도(장면 단위 길이 / 초) · 틀렸다가 지우고 다시 그릴 확률 · 중간에 멈칫할 확률 · 한 번 더 덧그릴 확률
CHILD_SPEED = {'기': 0.45, '승': 0.55, '전': 0.75, '결': 0.45}
CHILD_RETRY, CHILD_HESITATE, CHILD_OVERDRAW = 0.35, 0.25, 0.20
DRAW_DEADLINE = 0.80  # 오브제는 장면의 80% 안에 다 그리고, 나머지는 완성된 채로 머문다 (장면 끝 2.5초에 부드럽게 사라짐)


def _plan_strokes(items, start, act, prng):
    """오브제 하나의 획들을 언제 · 어떻게 그릴지 정한다 → (획마다 [(시작, 끝, 동작, 처음 비율, 끝 비율, 판)] , 다 그린 시각)"""
    t = start
    speed = CHILD_SPEED.get(act, 0.55)
    plans = []
    for k, it in enumerate(items):
        L = max(0.2, (len(it['pts']) - 1) * 0.03)
        td = max(0.5, L / speed)
        acts = [('pause', prng.uniform(0.6, 1.1) if k == 0 else prng.uniform(0.2, 0.6), 0.0, 0.0, 'ok')]  # 펜을 대고 망설임
        r = prng.random()
        if r < CHILD_RETRY:  # 비뚤게 그리다가 멈추고 → 지우고 → 다시 그린다
            f0 = prng.uniform(0.35, 0.7)
            acts += [('draw', td * f0, 0.0, f0, 'wrong'), ('pause', prng.uniform(0.5, 1.0), f0, f0, 'wrong'),
                     ('erase', max(0.4, td * f0 * 0.5), f0, 0.0, 'wrong'), ('pause', 0.3, 0.0, 0.0, 'ok'),
                     ('draw', td, 0.0, 1.0, 'ok')]
        elif r < CHILD_RETRY + CHILD_HESITATE:  # 그리다가 멈칫하고 이어 그린다
            f1 = prng.uniform(0.3, 0.7)
            acts += [('draw', td * f1, 0.0, f1, 'ok'), ('pause', prng.uniform(0.4, 0.9), f1, f1, 'ok'),
                     ('draw', td * (1 - f1), f1, 1.0, 'ok')]
        else:
            acts += [('draw', td, 0.0, 1.0, 'ok')]
        if prng.random() < CHILD_OVERDRAW:  # 한 번 더 덧그린다
            acts += [('draw', td * 0.6, 0.0, 1.0, 'over')]
        seq = []
        for typ, dur, f0, f1, var in acts:
            seq.append((t, t + dur, typ, f0, f1, var))
            t += dur
        plans.append(seq)
        it['wrong'] = (prng.uniform(-0.25, 0.25), prng.uniform(1.08, 1.2), prng.uniform(-0.06, 0.06), prng.uniform(-0.06, 0.06))
    return plans, t


def _stroke_state(seq, ts):
    """지금 시각의 획 상태 — 바른 획 비율 · 틀린 획 비율 · 덧그림 비율 · 펜(동작, 비율, 판) · 지우는 자국(지금, 처음, 남은 정도)"""
    ok = wrong = over = 0.0
    pen = smear = None
    for a, b, typ, f0, f1, var in seq:
        if ts < a:
            break
        p = 1.0 if ts >= b else (ts - a) / max(b - a, 1e-6)
        f = f0 + (f1 - f0) * p
        if var == 'over':
            over = f
        elif var == 'wrong':
            wrong = f
        else:
            ok = f
        if ts < b:
            pen = (typ, f, var)
            if typ == 'erase':
                smear = (f, f0, 1 - p)
    return ok, wrong, over, pen, smear


class LineScene:
    def __init__(self, S, files, keep, seed, scene_sec=75.0):
        self.S = S
        self.scene_sec = scene_sec
        self.L = LINE_ACT[S.act]
        order = LINE_EMO_ORDER.get(S.emo_label, LINE_EMO_ORDER['중립'])
        self.pal = [np.array(LINE_PAL[n], np.float32) / 255 for n in order]
        rng = np.random.default_rng(seed)
        self.glyphs = []
        for j, oi in enumerate(keep):
            strokes, rgb = extract_glyph(files[oi])
            beh = {k: v[j] for k, v in S.beh_arr.items()}
            marks = law_marks(beh)
            items = []
            r, g_, b = [c / 255 for c in rgb]
            sat = max(r, g_, b) - min(r, g_, b)
            main = self.pal[j % len(self.pal)]
            if sat > 0.18:  # 색이 뚜렷한 오브제(밤색 서류철 · 냉동액 등)는 그 색을 살린다
                import colorsys
                hh, ll, ss = colorsys.rgb_to_hls(r, g_, b)
                main = np.array(colorsys.hls_to_rgb(hh, 0.6, 0.85), np.float32)
            for k, (pts, w, kind) in enumerate(strokes):
                col = main if kind == 'body' and k == 0 else self.pal[(j + k + 2) % len(self.pal)]
                items.append(dict(pts=_densify(pts), w=w, col=col, kind=kind))
            for k, m in enumerate(marks):
                items.append(dict(pts=_densify(m), w=0.75, col=self.pal[(j + k + 4) % len(self.pal)], kind='mark'))
            if beh.get('precede'):  # 결과가 먼저 — 덧그림 기호부터 그린다
                items = [it for it in items if it['kind'] == 'mark'] + [it for it in items if it['kind'] != 'mark']
            self.glyphs.append(dict(items=items, beh=beh, size=float(max(S.sizes[j])) * self.L['scale']))
        # 그리는 계획 — 오브제마다 등장 시각부터 획을 하나씩 (펜 · 멈칫 · 틀림 · 지움 · 다시 그림 · 덧그림)
        prng = np.random.default_rng(seed + 101)
        for j, g in enumerate(self.glyphs):
            start = float(S.enter[j]) * scene_sec
            g['plan'], g['done_t'] = _plan_strokes(g['items'], start, S.act, prng)
            deadline = DRAW_DEADLINE * scene_sec  # 장면이 넘어가기 전에 완성되어 머무는 시간을 남긴다
            if g['done_t'] > deadline and g['done_t'] > start:
                k_ = max(0.2, (deadline - start) / (g['done_t'] - start))
                g['plan'] = [[(start + (a - start) * k_, start + (b - start) * k_, typ, f0, f1, var)
                              for a, b, typ, f0, f1, var in seq] for seq in g['plan']]
                g['done_t'] = start + (g['done_t'] - start) * k_
        # 크기 변화 계획 — 오브제마다 숨쉬기 주기 · 부풀 시각 (스토리 시드로 정해져 같은 스토리면 같다)
        for j, g in enumerate(self.glyphs):
            g['breath'] = (prng.uniform(6.0, 11.0), prng.uniform(0, 2 * np.pi))
            sw, t_ = [], float(S.enter[j]) * scene_sec + prng.uniform(8.0, 16.0)
            while t_ < scene_sec - 6:
                sw.append((t_, prng.uniform(4.0, 6.0), SIZE_SWELL.get(S.act, 0.3) * prng.uniform(0.7, 1.0)))
                t_ += prng.uniform(18.0, 30.0)
            g['swell'] = sw
        # 메아리 — 이 장면 오브제 조각이 작게 그려졌다 사라진다 (언제 · 어디서 · 무엇을 · 얼마나 크게)
        dur = 1.0
        n_echo = int(self.L['echo_rate'] * 75)
        self.echo = []
        for e in range(n_echo):
            j = int(rng.integers(0, max(1, len(self.glyphs))))
            if not self.glyphs or not self.glyphs[j]['items']:
                continue
            it = self.glyphs[j]['items'][int(rng.integers(0, len(self.glyphs[j]['items'])))]
            t0 = rng.uniform(0.02, 0.92)
            if S.act == '전':  # 절정으로 갈수록 크고 많아진다 — 반전 직전에 몰린다
                t0 = 0.05 + 0.85 * rng.random() ** 0.6
            self.echo.append(dict(it=it, t0=t0, life=rng.uniform(2.5, 5.0) / 75 * dur,
                                  x=rng.uniform(0.08, 0.92), y=rng.uniform(0.12, 0.88),
                                  size=rng.uniform(*self.L['echo_size']), ang=rng.uniform(-0.6, 0.6),
                                  seed=float(rng.uniform(0, 100))))

    def size_mult(self, j, u, t):
        """지금 이 오브제의 크기 배율 — 숨쉬기 × 부풀기 × 법칙 흐름 × (전) 반전 전 부풀기"""
        S, g = self.S, self.glyphs[j]
        per, ph = g['breath']
        m = 1 + SIZE_BREATH.get(S.act, 0.12) * math.sin(2 * math.pi * t / per + ph)
        for t0, dur, amp in g['swell']:
            if t0 <= t <= t0 + dur:
                m *= 1 + amp * math.sin(math.pi * (t - t0) / dur) ** 2
        span = max(float(S.dissolve[j] - S.enter[j]), 1e-3)
        prog = min(1.0, max(0.0, (u - float(S.enter[j])) / span))
        m *= 1 + sum(v * prog for k, v in SIZE_TREND.items() if g['beh'].get(k))
        if S.rev is not None:
            lead = 6.0 / self.scene_sec
            if S.rev - lead <= u < S.rev:
                m *= 1 + 0.30 * float(smoothstep(S.rev - lead, S.rev, u))
        return min(1.9, max(0.5, m))  # 화면 밖으로 넘치거나 점처럼 줄지 않게

    def _xf(self, pts, j, F, dx, dy, sx, tilt, scale, stretch, gap, flut, t):
        S = self.S
        g = self.glyphs[j]
        p = pts.copy()
        p[:, 1] = np.where(p[:, 1] > 0, p[:, 1] * (1 + stretch[j]), p[:, 1])
        p[:, 0] = p[:, 0] + flut[j] / max(g['size'], 1) * np.sin(p[:, 1] * 9 + 6 * t) * np.abs(p[:, 0]) * 2
        p = p * (g['size'] * self.mult[j])
        p[:, 0] *= sx[j] * scale[j]
        p[:, 1] *= scale[j]
        c, s = math.cos(tilt[j]), math.sin(tilt[j])
        x = S.anchors[j, 0] + dx[j] + p[:, 0] * c - p[:, 1] * s
        y = S.anchors[j, 1] + dy[j] + p[:, 0] * s + p[:, 1] * c
        return np.stack([x, y], 1)

    def render(self, frame, u, t, composite):
        S = self.S
        W, H = S.W, S.H
        F, dx, dy, sx, tilt, scale, stretch, gap, flut = S.transforms(u, t)
        flip, pull, cmix = S.rev_phase(u)
        burst = (1 - min(1.0, pull)) if flip else 0.0
        self.mult = [self.size_mult(j, u, t) for j in range(len(self.glyphs))]
        tq = math.floor(t * 8) / 8  # 손그림처럼 1초에 8번 떨린다
        thick = max(2, int(H * 0.0075 * self.L['thick']))
        layer = np.zeros((H, W, 3), np.float32)
        mask = np.zeros((H, W), np.float32)
        tint = S.rev_tint

        def stroke(pts, col, w, frac, seed, amp, alpha=1.0, dash=False):
            if frac <= 0 or len(pts) < 2:
                return
            n = max(2, int(math.ceil(len(pts) * min(1.0, frac))))
            q = pts[:n]
            if cmix > 0:
                col = col * (1 - cmix) + tint * cmix
            P = q.astype(np.int32).reshape(-1, 1, 2)
            th = max(1, int(thick * w))
            if dash:  # 바스러지는 중 — 끊어진 짧은 선
                for a0 in range(0, n - 1, 4):
                    seg = P[a0:a0 + 2]
                    cv2.polylines(layer, [seg], False, (col * alpha).tolist(), th, cv2.LINE_AA)
                    cv2.polylines(mask, [seg], False, alpha, th + 6, cv2.LINE_AA)
                return
            cv2.polylines(layer, [P], False, (col * alpha).tolist(), th, cv2.LINE_AA)
            cv2.polylines(mask, [P], False, alpha, th + 6, cv2.LINE_AA)

        pens = []

        def at(pts, frac):
            return pts[min(len(pts) - 1, max(0, int(round((len(pts) - 1) * frac))))]

        def burst_off(pts, j):
            if burst <= 0:
                return pts
            d = pts - S.anchors[j]
            return pts + d / (np.linalg.norm(d, axis=1, keepdims=True) + 1) * (H * 0.45 * burst)

        for j, g in enumerate(self.glyphs):
            items = g['items']
            if not items:
                continue
            beh = g['beh']
            n = len(items)
            # 다 그린 오브제는 장면 끝까지 완성된 채로 머물다가, 마지막 2.5초에 부드럽게 사라진다 (지우개로 지우지 않음)
            fade = 1.0 - float(smoothstep(self.scene_sec - 2.5, self.scene_sec - 0.2, t))
            if fade <= 0:
                continue
            amp = 0.0 if beh.get('still') else 0.006 * g['size']
            for k, it in enumerate(items):
                ok, wrong, over, pen, smear = _stroke_state(g['plan'][k], t)
                if ok <= 0 and wrong <= 0 and pen is None and smear is None:
                    continue
                col = it['col']
                frac = ok
                a_ = fade
                if beh.get('flicker') and ok >= 1:  # 있다 없다 — 획이 사라지지 않고 1.4초마다 희미해졌다 돌아온다
                    if ((k * 2654435761 + int(t / 1.4) * 40503 + j * 97) % 7) <= 2:
                        a_ *= 0.35
                base = _wobble(it['pts'], amp / max(g['size'], 1), k * 3.7 + j, tq)
                pts = burst_off(self._xf(base, j, F, dx, dy, sx, tilt, scale, stretch, gap, flut, t), j)
                stroke(pts, col, it['w'], frac, k, amp, alpha=a_)
                # 틀린 획 — 조금 돌아가고 커지고 비켜난 자리에 그렸다가 지운다
                if wrong > 0 or (smear is not None and pen and pen[2] == 'wrong'):
                    rot, sc_, ox, oy = it['wrong']
                    c_, s_ = math.cos(rot), math.sin(rot)
                    wp = base @ np.array([[c_, s_], [-s_, c_]], np.float32) * sc_ + np.array([ox, oy], np.float32)
                    wpts = burst_off(self._xf(wp, j, F, dx, dy, sx, tilt, scale, stretch, gap, flut, t), j)
                    stroke(wpts, col * 0.9, it['w'], wrong, k, amp, alpha=fade)
                    if smear is not None:  # 지우는 중 — 지운 자리에 옅은 자국이 잠깐 남는다
                        f_now, f_from, left = smear
                        i0, i1 = int((len(wpts) - 1) * f_now), int((len(wpts) - 1) * f_from) + 1
                        if i1 - i0 >= 2:
                            stroke(wpts[i0:i1], col, it['w'] * 0.8, 1.0, k, amp, alpha=0.22 * left)
                    if pen and pen[2] == 'wrong':
                        pens.append((pen[0], at(wpts, pen[1]), j, k, pen[1]))
                if over > 0:  # 덧그림 — 살짝 비켜난 자리에 가늘게 한 번 더
                    op = burst_off(self._xf(base + np.array([0.012, -0.01], np.float32), j, F, dx, dy, sx, tilt, scale, stretch, gap, flut, t), j)
                    stroke(op, col, it['w'] * 0.55, over, k, amp, alpha=0.85 * fade)
                    if pen and pen[2] == 'over':
                        pens.append((pen[0], at(op, pen[1]), j, k, pen[1]))
                if pen and pen[2] == 'ok':
                    pens.append((pen[0], at(pts, pen[1]), j, k, pen[1]))
        # 펜 · 지우개 — 그리는 손이 보이게 (펜 = 밝은 점 · 지우개 = 빈 동그라미)
        for kind, p, j, k, f in pens:
            if p is None:
                continue
            x, y = int(p[0]), int(p[1])
            r = max(3, int(thick * 0.9))
            if kind == 'erase':
                cv2.circle(layer, (x, y), int(r * 1.9), (0.85, 0.85, 0.9), max(1, thick // 3), cv2.LINE_AA)
                cv2.circle(mask, (x, y), int(r * 2.2), 0.8, -1, cv2.LINE_AA)
            else:
                cv2.circle(layer, (x, y), r, (1.0, 1.0, 0.95), -1, cv2.LINE_AA)
                cv2.circle(layer, (x, y), int(r * 2.2), (0.35, 0.35, 0.3), max(1, thick // 4), cv2.LINE_AA)
                cv2.circle(mask, (x, y), int(r * 2.2), 0.9, -1, cv2.LINE_AA)
        # 메아리
        for e in self.echo:
            a = (u - e['t0']) / e['life']
            if a <= 0 or a >= 1:
                continue
            frac = min(1.0, a / 0.4)
            alpha = 1.0 if a < 0.75 else (1 - a) / 0.25
            it = e['it']
            sz = e['size'] * min(H, W) * 0.5 * (0.55 + 0.9 * a)  # 작게 나타나 커지며 사라진다
            p = _wobble(it['pts'], 0.01, e['seed'], tq) * sz
            c, s = math.cos(e['ang']), math.sin(e['ang'])
            P = np.stack([e['x'] * W + p[:, 0] * c - p[:, 1] * s, e['y'] * H + p[:, 0] * s + p[:, 1] * c], 1)
            if burst > 0:
                d = P - [W / 2, H / 2]
                P = P + d / (np.linalg.norm(d, axis=1, keepdims=True) + 1) * (H * 0.5 * burst)
            stroke(P, it['col'], 0.55 + 0.6 * e['size'], frac, 0, 0, alpha=alpha)
        # 선 둘레의 어두운 받침 → 선 → 은은한 빛
        q = (max(8, W // 4), max(8, H // 4))
        halo = cv2.resize(cv2.GaussianBlur(cv2.resize(mask, q, interpolation=cv2.INTER_AREA), (0, 0), 7 * H / 1080 + 2), (W, H))
        halo = np.clip(halo * 2.5, 0, 1)
        frame = frame * (1 - 0.55 * halo[..., None])
        cover = np.clip(cv2.GaussianBlur(mask, (0, 0), 0.8) * 1.2, 0, 1) if False else None
        lum = np.clip(layer.max(2, keepdims=True), 0, 1)
        frame = frame * (1 - lum) + layer
        glow = cv2.resize(cv2.GaussianBlur(cv2.resize(layer, q, interpolation=cv2.INTER_AREA), (0, 0), 3 * H / 1080 + 1), (W, H))
        frame = frame + glow * 0.35
        return frame


# ─────────────────────────────────────────────────────────────
# 8. 하나의 오브제 (선화 기본 · 10/24 교수님 피드백)
#    "어린아이가 무작위 기하 도형을 그렸다 지웠다를 반복하다가 마침내 무언가를 창조하는 과정 · 창작의 괴로움 ·
#     꿈 스토리에 따라 다양한 형상으로 변해 가는 과정 · 오브제는 하나만 — 시선이 한곳에 머물게"
#    장면 1: 펜이 머뭇거리다 → 무작위 도형(원·삼각·사각·별·나선·지그재그…)을 그렸다 지우고, 덧칠해 지우고, 희미하게 남기고…
#            시도할수록 도형이 대본의 첫 오브제 모양을 닮아 가다가 → 마침내 첫 오브제를 그려 낸다
#    그다음: 같은 오브제가 대본의 다음 오브제들로 차례로 변한다 (획을 지우고 다시 긋거나 · 획이 휘어져 다른 모양이 됨)
#    장면 2~4: 앞 장면의 마지막 모양에서 시작해 머뭇거리다 → 이 장면의 오브제들로 변해 간다
#    스토리 법칙은 지금 모양의 움직임(떠오름 · 회전 · 늘어남 · 가라앉음 …)과 덧그림 기호로 드러난다
# ─────────────────────────────────────────────────────────────
ONE_N = 72                     # 모양을 맞대어 바꿀 때 획 하나를 나누는 점 수
# 배경 엔진의 감정 색 (기쁨 금빛 · 슬픔 깊은 파랑 · 분노 붉음 · 공포 남보라 · 놀람 자홍 · 혐오 탁한 풀빛)
EMO_HUE = {'기쁨': (1.0, 0.82, 0.45), '슬픔': (0.45, 0.6, 1.0), '분노': (1.0, 0.45, 0.4), '공포': (0.62, 0.55, 1.0),
           '놀람': (1.0, 0.5, 0.85), '혐오': (0.62, 0.85, 0.45), '중립': (0.85, 0.86, 0.92)}
ONE_TINT = 0.35      # 선 색에 배경 감정 색을 섞는 정도 — 사람의 선이지만 같은 꿈의 색으로 물든다
ONE_BG_MIX = 0.5     # 배경 영상 위에 그릴 때: 오브제 둘레의 실제 배경 색을 읽어 선 색을 이만큼 그 색 계열로 맞춘다
# 진화 모드 색 (배경 담당 색표 10/27) — 배경 장면의 주색(색상) 기준:
#   같은 색 60% (윤곽 · 몸통) · 비슷한 색 ±30° 30% (세부 · 그물망 · 누런 초록으로 가면 반대쪽) · 반대색 10% (덧그림 · 장식)
#   파스텔이 아니게 채도를 높게, 밝기는 배경과 반대 (밝은 배경엔 짙은 선 · 어두운 배경엔 밝은 선)
COLOR_SAT = 0.82
# 배경 담당 색표 (10/27 새 배경 엔진 실측 주색) — 화면에서 읽은 색이 무채색에 가까우면 이 값을 쓴다
EMO_BG_HUE = {'놀람': 322, '공포': 247, '기쁨': 37, '슬픔': 217, '분노': 8, '혐오': 95, '중립': 220}
COLOR_Y_ON_DARK, COLOR_Y_ON_BRIGHT = 0.6, 0.2
ONE_BG_EMA = 0.04    # 배경 색을 따라가는 속도 (프레임당) — 1초쯤에 걸쳐 천천히 따라가 깜빡이지 않게
ONE_DUST = 3.0       # 지운 선이 배경 같은 점으로 흩어져 남는 시간(초) — 사람의 획이 기계의 점이 된다
# 꿈의 변형 — 형상이 드러난 순간(시작점)만 그 물체이고, 곧 꿈의 논리로 흐트러진다 (정적인 물체 그 자체로 머물지 않게)
#   드러난 뒤 1.5초는 그 물체 → 6초에 걸쳐 변형이 차오름 → 이후 9.5초 주기로 '거의 알아볼 듯'과 '낯섦' 사이를 오간다
#   획마다 따로 떠다니고 · 돌고 · 늘었다 줄고, 선 자체도 물결처럼 일렁인다. 스토리 법칙이 변형의 방향을 정한다
DREAM_MAX = {'기': 0.7, '승': 0.8, '전': 1.0, '결': 0.9}
# 진화 (11/05 교수님 피드백) — 목표 선화(targets.json)를 향해 흩어진 점들이 세대를 거듭하며 다가간다
EVO_N = 1800          # 점(개체) 수
EVO_GEN = 1 / 15      # 한 세대 시간(초)
EVO_STEP = 0.012      # 목표 선화를 점으로 나누는 간격 (단위 상자 기준)
EVO_RINGS = 0.28      # 형상 둘레의 동심원 · 작은 원 · 점 (교수님 예시 선화의 배경 장식) 밝기 · 0 이면 끔
# 유전 알고리즘 (정상 상태 GA) — 개체 = 점 하나의 위치(유전자 x, y) · 적합도 = −(목표 선 위 자기 자리까지 거리)
#   세대마다: ① 변이(가우스) 후 적합도가 나아진 개체만 남김(선택) ② 적합도 하위 GA_REPLACE 를 도태시키고,
#   상위 개체 둘(같은 선의 이웃 자리 · 순위 선택)을 교차(무작위 비율 섞기)해 자식으로 바꿔 넣음 ③ 상위 GA_ELITE 는 그대로(엘리트 보존)
GA_REPLACE = 0.06     # 세대마다 도태 · 교체되는 비율
GA_ELITE = 0.10       # 변이 없이 보존되는 상위 비율
ONE_ACT_SIZE = {'기': 0.90, '승': 1.0, '전': 1.10, '결': 0.95}   # 장면별 크기 (화면 높이의 0.46배 × 이 값)
ONE_BUDGET = {'search': 0.30, 'create': 0.50}  # 장면 1: 탐색은 장면의 30% 안 · 첫 오브제 완성은 50% 안 (나머지는 변해 가는 시간)


def _resample(pts, n=ONE_N):
    pts = np.asarray(pts, np.float32)
    if len(pts) < 2:
        return np.repeat(pts[:1] if len(pts) else np.zeros((1, 2), np.float32), n, 0)
    seg = np.hypot(*(pts[1:] - pts[:-1]).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    if s[-1] <= 1e-6:
        return np.repeat(pts[:1], n, 0)
    q = np.linspace(0, s[-1], n)
    return np.stack([np.interp(q, s, pts[:, 0]), np.interp(q, s, pts[:, 1])], 1).astype(np.float32)


def _primitive(rng):
    """어린아이가 그어 보는 무작위 기하 도형 (단위 상자 · 가운데 0)"""
    kind = rng.choice(['circle', 'triangle', 'square', 'pentagon', 'star', 'spiral', 'zigzag', 'wave', 'cross', 'lens'])
    t = np.linspace(0, 1, 60)
    if kind == 'circle':
        p = np.stack([np.cos(2 * np.pi * t), np.sin(2 * np.pi * t)], 1) * 0.45
    elif kind in ('triangle', 'square', 'pentagon'):
        k = {'triangle': 3, 'square': 4, 'pentagon': 5}[kind]
        a = np.linspace(0, 2 * np.pi, k + 1) + rng.uniform(0, np.pi)
        p = np.stack([np.cos(a), np.sin(a)], 1) * 0.47
    elif kind == 'star':
        a = np.linspace(0, 2 * np.pi, 11)
        r = np.where(np.arange(11) % 2 == 0, 0.48, 0.2)
        p = np.stack([np.cos(a) * r, np.sin(a) * r], 1)
    elif kind == 'spiral':
        a = t * 4 * np.pi
        p = np.stack([np.cos(a), np.sin(a)], 1) * (0.05 + 0.42 * t)[:, None]
    elif kind == 'zigzag':
        x = np.linspace(-0.45, 0.45, 9)
        p = np.stack([x, np.where(np.arange(9) % 2 == 0, -0.2, 0.2)], 1)
    elif kind == 'wave':
        x = np.linspace(-0.45, 0.45, 40)
        p = np.stack([x, 0.15 * np.sin(x * 4 * np.pi)], 1)
    elif kind == 'cross':
        p = np.array([[-0.4, -0.4], [0.4, 0.4], [0.0, 0.0], [0.4, -0.4], [-0.4, 0.4]])
    else:  # lens
        a = np.linspace(0, np.pi, 30)
        top = np.stack([np.cos(a) * 0.45, -np.sin(a) * 0.25], 1)
        p = np.vstack([top, top[::-1] * [1, -1]])
    return np.asarray(p, np.float32), kind


def _blend(a, b, w):
    """도형 a 를 모양 b 쪽으로 w 만큼 닮게 — 시작점을 맞춘 뒤 점끼리 섞는다"""
    A, B = _resample(a), _resample(b)
    best, sh = None, 0
    for s in range(0, ONE_N, 4):  # 닫힌 도형이면 시작점을 돌려 가장 가까운 짝을 찾는다
        d = np.abs(np.roll(A, s, 0) - B).sum()
        if best is None or d < best:
            best, sh = d, s
    return np.roll(A, sh, 0) * (1 - w) + B * w


def _one_form(path, beh, main_col, accent_col):
    """PNG → '하나의 오브제' 모양: 가장 큰 덩어리 윤곽 + 그 안의 큰 선 2개 + 법칙 기호 1개 (떨어진 조각은 버린다)"""
    strokes, _ = extract_glyph(path)
    bodies = [p for p, w, k in strokes if k == 'body']
    if not bodies:
        return None
    body = bodies[0]
    mn, mx = body.min(0), body.max(0)
    pad = (mx - mn) * 0.1
    inners = [p for p, w, k in strokes if k == 'inner'
              and np.all(p.mean(0) >= mn - pad) and np.all(p.mean(0) <= mx + pad)][:2]
    c = (mn + mx) / 2
    s = float(max(mx - mn)) or 1.0
    norm = lambda p: (np.asarray(p, np.float32) - c) / s
    items = [(_resample(norm(body)), 1.0, 'body')] + [(_resample(norm(p)), 0.7, 'inner') for p in inners]
    marks = law_marks(beh)[:1]
    items += [(_resample(m), 0.7, 'mark') for m in marks]
    cols = [main_col] + [accent_col] * (len(items) - 1)
    return dict(items=items, cols=cols, beh=beh)


def _doodle_form(entry, beh, main_col, accent_col, max_strokes=10):
    """손그림 형상(사람이 그은 획 순서 그대로) → 모양. 법칙 기호 1개를 덧붙인다"""
    strokes = [np.asarray(st, np.float32) for st in (entry.get('strokes') or []) if len(st) >= 2][:max_strokes]
    if not strokes:
        return None
    items = [(_resample(p), 1.0 if k == 0 else 0.85, 'body' if k == 0 else 'inner') for k, p in enumerate(strokes)]
    items += [(_resample(m), 0.7, 'mark') for m in law_marks(beh)[:1]]
    cols = [main_col] * len(strokes) + [accent_col] * (len(items) - len(strokes))
    alts = [[np.asarray(st, np.float32) for st in a if len(st) >= 2] for a in (entry.get('alts') or [])]
    return dict(items=items, cols=cols, beh=beh, name=entry.get('name', ''), category=entry.get('category', ''),
                reveal=float(entry.get('reveal', 0.5)), alts=[a for a in alts if a])


def _match(a, b):
    """휘어 바꿀 때 점 짝 맞추기 — 닫힌 획끼리는 시작점을 돌려 맞추고, 열린 획은 정방향 · 역방향 중 가까운 쪽"""
    A, B = _resample(a), _resample(b)
    closed = lambda P: np.hypot(*(P[0] - P[-1])) < 0.08
    if closed(A) and closed(B):
        return _blend(A, B, 0.0)
    return A if np.abs(A - B).sum() <= np.abs(A[::-1] - B).sum() else A[::-1].copy()


class OneObjectScene:
    def __init__(self, S, files, keep, seed, scene_sec, prev_files=None, is_last=False, doodle_scene=None, prev_doodle=None,
                 target_scene=None, prev_target=None):
        self.S = S
        self.is_last = is_last
        self.scene_sec = T = scene_sec
        self.L = LINE_ACT[S.act]
        order = LINE_EMO_ORDER.get(S.emo_label, LINE_EMO_ORDER['중립'])
        self.hue = np.array(EMO_HUE.get(S.emo_label, EMO_HUE['중립']), np.float32)
        self.pal = [np.array(LINE_PAL[n], np.float32) / 255 * (1 - ONE_TINT) + self.hue * ONE_TINT for n in order]
        rng = np.random.default_rng(seed + 202)
        self.rng = rng
        # 대본의 오브제들 = 하나의 오브제가 거쳐 갈 모양들 (모양마다 주된 색 하나 + 보조색 하나)
        self.stages = []
        for j, oi in enumerate(keep):
            beh = {k: v[j] for k, v in S.beh_arr.items()}
            f = _one_form(files[oi], beh, self.pal[j % len(self.pal)], self.pal[(j + 3) % len(self.pal)])
            if f is not None:
                f['name'] = S.names[oi] if oi < len(S.names) else ''
                self.stages.append(f)
        prev = None
        for pf in reversed(list(prev_files or [])):  # 앞 장면에서 모양이 만들어지는 마지막 오브제 (빈 PNG 는 건너뜀)
            prev = _one_form(pf, {}, self.pal[2 % len(self.pal)], self.pal[5 % len(self.pal)])
            if prev is not None:
                break
        # 손그림 형상 (doodles.json) 이 있으면 그걸 쓴다 — 알아볼 수 있는 형상 · 이야기에 나오는 자리에서 드러남
        self.mode = 'outline'
        self.finale_t = None
        if doodle_scene:
            dst = []
            for j, e in enumerate(doodle_scene):
                beh = {k: (v[j] if j < len(v) else False) for k, v in S.beh_arr.items()}
                f = _doodle_form(e, beh, self.pal[j % len(self.pal)], self.pal[(j + 3) % len(self.pal)])
                if f is not None:
                    dst.append(f)
            if dst:
                dst.sort(key=lambda f: f['reveal'])  # 이야기에 나오는 순서대로
                self.stages, self.mode = dst, 'doodle'
                prev = _doodle_form(prev_doodle, {}, self.pal[2 % len(self.pal)], self.pal[5 % len(self.pal)]) if prev_doodle else None
        self.inst = []   # 그려지는 획들 — dict(pts | pts2, col, w, d0, d1, e0, e1, m0, m1, ghost)
        self.hover = []  # 펜이 멈춰 머뭇거리는 구간 — (t0, t1, 위치)
        self.stage_t = []  # (모양이 바뀌기 시작한 시각, 단계 번호)
        if target_scene and any(o.get('strokes') for o in target_scene):
            self._init_evolve(target_scene, prev_target, seed)
            return
        if self.mode == 'doodle':
            self._build_doodle(prev)
        else:
            self._build(prev)

    # ── 시간표 만들기 ─────────────────────────────────────
    def _add(self, pts, col, w, d0, d1, **kw):
        it = dict(pts=np.asarray(pts, np.float32), col=np.asarray(col, np.float32), w=w, d0=d0, d1=d1,
                  e0=None, e1=None, m0=None, m1=None, pts2=None, ghost=None, uid=len(self.inst))
        it.update(kw)
        self.inst.append(it)
        return it

    def _squeeze(self, t0, t_now, t_goal):
        """t0 이후의 동작들이 t_goal 안에 끝나도록 시간을 줄인다"""
        if t_now <= t_goal or t_now <= t0:
            return t_now
        k = (t_goal - t0) / (t_now - t0)
        f = lambda x: x if (x is None or x < t0) else t0 + (x - t0) * k
        for it in self.inst:
            for a in ('d0', 'd1', 'e0', 'e1', 'm0', 'm1'):
                it[a] = f(it[a])
            if it.get('ghost'):
                it['ghost'] = (f(it['ghost'][0]), f(it['ghost'][1]))
            if it.get('pause'):
                it['pause'] = (it['pause'][0], it['pause'][1] * k)
        self.hover = [(f(a), f(b), p) for a, b, p in self.hover]
        return t_goal

    def _dur(self, pts, speed):
        L = float(np.hypot(*(pts[1:] - pts[:-1]).T).sum()) if len(pts) > 1 else 0.2
        return float(np.clip(L / speed, 0.5, 4.0))

    def _build(self, prev):
        S, rng, T = self.S, self.rng, self.scene_sec
        speed = CHILD_SPEED.get(S.act, 0.55) * 1.2
        grey = np.array([0.86, 0.87, 0.92], np.float32)
        t = rng.uniform(0.8, 1.4)
        if not self.stages:
            return
        target = self.stages[0]
        main = target['items'][0][0]
        current = []  # 지금 화면에 남아 있는(완성된) 획들
        if prev is None:
            # ① 괴로운 탐색 — 무작위 도형을 그렸다 지우기를 되풀이하며 첫 오브제 모양을 닮아 간다
            self.hover.append((0.0, t, np.zeros(2, np.float32)))
            n_att = int(rng.integers(5, 9))
            ghosts = []
            for i in range(n_att):
                w = 0.08 + 0.8 * (i / max(n_att - 1, 1)) ** 1.3        # 시도할수록 첫 오브제를 닮는다
                prim, kind = _primitive(rng)
                spread = 0.35 * (1 - w)                                 # 처음엔 여기저기 · 점점 가운데로
                off = rng.uniform(-spread, spread, 2).astype(np.float32)
                sc = rng.uniform(0.55, 1.25) * (1 - 0.5 * w) + 0.5 * w
                rot = rng.uniform(-np.pi, np.pi) * (1 - w)
                c_, s_ = math.cos(rot), math.sin(rot)
                shape = _blend(prim, main, w) @ np.array([[c_, s_], [-s_, c_]], np.float32) * sc + off
                col = grey * (1 - w) + self.pal[0] * w
                d = self._dur(shape, speed) * rng.uniform(0.7, 1.3)
                if rng.random() < 0.35:   # 그리다 말고 멈춘다
                    part = rng.uniform(0.35, 0.75)
                    it = self._add(shape[:max(2, int(ONE_N * part))], col, 0.95, t, t + d * part)
                    t += d * part
                else:
                    it = self._add(shape, col, 0.95, t, t + d)
                    t += d
                hold = rng.uniform(0.5, 1.6)
                self.hover.append((t, t + hold, None))                 # 펜을 들고 바라본다 (끝점에서 머뭇)
                t += hold
                r = rng.random()
                if r < 0.25:   # 마음에 안 들어 박박 덧칠하고 지운다
                    scr = np.stack([np.linspace(-0.4, 0.4, 14), np.where(np.arange(14) % 2 == 0, -0.25, 0.25)], 1) * sc + off
                    sc_it = self._add(scr, col * 0.8, 0.9, t, t + 0.6)
                    t += 0.7
                    e = rng.uniform(0.6, 1.0)
                    it['e0'], it['e1'] = t, t + e
                    sc_it['e0'], sc_it['e1'] = t, t + e
                    t += e + rng.uniform(0.2, 0.6)
                elif r < 0.82:  # 지운다
                    e = rng.uniform(0.6, 1.4)
                    it['e0'], it['e1'] = t, t + e
                    t += e + rng.uniform(0.2, 0.7)
                else:           # 희미하게 남겨 둔다 (나중에 함께 지운다)
                    it['ghost'] = (t, t + 2.5)
                    ghosts.append(it)
                    t += rng.uniform(0.3, 0.8)
            t = self._squeeze(0.0, t, ONE_BUDGET['search'] * T)
            # ② 마침내 — 첫 오브제를 그려 낸다 (멈칫 · 틀렸다 고치기 포함)
            for g in ghosts:
                g['e0'], g['e1'] = t, t + 0.9
            t += 0.6
            t_c = t
            current = self._draw_form(target, t, speed * 1.6)
            t = max(it['d1'] for it in current)
            t = self._squeeze(t_c, t, ONE_BUDGET['create'] * T - 1.5) + rng.uniform(1.0, 2.0)
        else:
            # 앞 장면의 마지막 모양이 그대로 남아 있다 → 머뭇거리며 몇 군데 지웠다 다시 그어 본다
            for k, (p, w, kind) in enumerate(prev['items']):
                current.append(self._add(p, prev['cols'][k], w, -2.0, -1.0))
            self.hover.append((0.0, t, np.zeros(2, np.float32)))
            for _ in range(int(rng.integers(1, 3))):
                prim, kind = _primitive(rng)
                shape = _blend(prim, main, rng.uniform(0.2, 0.5)) * rng.uniform(0.5, 0.9)
                d = self._dur(shape, speed)
                it = self._add(shape, grey, 0.75, t, t + d)
                t += d + rng.uniform(0.4, 1.0)
                it['e0'], it['e1'] = t, t + rng.uniform(0.6, 1.0)
                t = it['e1'] + rng.uniform(0.2, 0.5)
            self.stage_t.append((t, -1))
            t_c = t
            current, t = self._transform(current, target, t, speed * 1.6)
            t = self._squeeze(t_c, t, 0.32 * T)
        self.stage_t.append((t - 0.01, 0))
        # ③ 꿈 스토리 — 같은 오브제가 대본의 다음 오브제들로 차례로 변해 간다
        #    장면 끝까지 고르게 나눠 바뀌고, 머무는 동안에도 아이가 계속 고쳐 그린다 (멈춰 있는 시간이 없게)
        rest = self.stages[1:]
        end = T * (0.93 if self.is_last else 0.97)
        t_base = t
        if rest:
            per = max(4.0, (end - t_base) / len(rest))
            for j, st in enumerate(rest, 1):
                t_start = max(t, t_base + (j - 1) * per + per * 0.35)
                t = self._vary_until(current, t, t_start)
                self.stage_t.append((t_start, j))
                current, t2 = self._transform(current, st, t_start, speed * 1.6)
                t = self._squeeze(t_start, t2, max(t_start + 2.0, t_base + j * per - 0.5))
        self._vary_until(current, t, end)
        self.current_end = current

    def _frag(self, p, amount):
        """형상의 획 하나를 알아보기 어렵게 — 돌리고 · 키우고/줄이고 · 옮긴 조각 (amount 0 = 제자리)"""
        rng = self.rng
        rot = rng.uniform(-np.pi, np.pi) * amount
        sc_ = 1 + rng.uniform(-0.45, 0.5) * amount
        c_, s_ = math.cos(rot), math.sin(rot)
        q = (p - p.mean(0)) @ np.array([[c_, s_], [-s_, c_]], np.float32) * sc_ + p.mean(0)
        return q + rng.uniform(-0.38, 0.38, 2).astype(np.float32) * amount

    def _build_doodle(self, prev):
        """손그림 형상의 꿈 —
        ① 처음엔 형상이 드러나지 않는다: 그 형상의 획들이 엉뚱한 자리 · 각도로 조각조각 그어졌다 지워지기를 되풀이하고
        ② 이야기에 그 오브제가 나오는 자리에서 조각들이 제자리를 찾아 형상이 드러난다
        ③ 다음 오브제가 이야기에 나올 때까지 형상이 조각으로 풀리며 흔들리다가 → 다음 형상으로 모인다"""
        S, rng, T = self.S, self.rng, self.scene_sec
        speed = CHILD_SPEED.get(S.act, 0.55) * 1.6
        end = T * (0.93 if self.is_last else 0.97)
        n = len(self.stages)
        # 형상이 드러나는 시각 — 이야기에서 그 오브제가 처음 나오는 자리 (겹치지 않게 최소 간격)
        lo = 0.30 * T if prev is None else 0.16 * T
        margin = min(6.0, 0.08 * T)                       # 짧은 시험(장면 10초)에서도 장면 안에 들어오게
        hi = max(lo + 0.5, end - margin)
        rev = [lo + (hi - lo) * min(1.0, max(0.0, st['reveal'])) for st in self.stages]
        gap = min(12.0, (hi - lo) / max(n, 1))
        for j in range(n):
            rev[j] = max(rev[j], lo if j == 0 else rev[j - 1] + gap)
        if rev[-1] > hi:
            rev = [lo + (r - lo) * (hi - lo) / max(rev[-1] - lo, 1e-3) for r in rev]
        self.reveal_t = rev
        grey = np.array([0.86, 0.87, 0.92], np.float32)
        t = rng.uniform(0.8, 1.4)
        self.hover.append((0.0, t, np.zeros(2, np.float32)))
        target = self.stages[0]
        current = []
        if prev is None:
            # ① 형상이 숨어 있다 — 첫 형상의 획들을 조각조각 엉뚱하게 그어 보고 지운다 (점점 제자리에 가까워짐)
            t_stop = rev[0] - 6.0
            i = 0
            while t < t_stop:
                prog = min(1.0, t / max(t_stop, 1.0))
                amount = 1.0 - 0.75 * prog
                ks = rng.choice(len(target['items']), size=min(len(target['items']), int(rng.integers(1, 3))), replace=False)
                drawn = []
                for k in ks:
                    src = target['items'][k][0]
                    if target.get('alts') and rng.random() < 0.45:   # 다른 갈래의 획 — 여러 가능성을 더듬는다
                        alt = target['alts'][int(rng.integers(len(target['alts'])))]
                        src = _resample(alt[int(rng.integers(len(alt)))])
                    p = self._frag(src, amount)
                    if rng.random() < 0.3:      # 가끔은 형상과 상관없는 도형도 그어 본다
                        prim, _ = _primitive(rng)
                        p = _blend(prim, p, prog * 0.6)
                    col = grey * (1 - prog) + target['cols'][0] * prog
                    d = self._dur(p, speed) * rng.uniform(0.8, 1.4)
                    part = 1.0 if rng.random() < 0.65 else rng.uniform(0.4, 0.8)
                    drawn.append(self._add(p[:max(2, int(ONE_N * part))], col, 0.9, t, t + d * part))
                    t += d * part + rng.uniform(0.15, 0.5)
                hold = rng.uniform(0.6, 1.8)
                self.hover.append((t, t + hold, None))
                t += hold
                r = rng.random()
                if r < 0.2:                       # 박박 덧칠하고 지운다
                    ctr = drawn[-1]['pts'].mean(0)
                    scr = np.stack([np.linspace(-0.3, 0.3, 12), np.where(np.arange(12) % 2 == 0, -0.15, 0.15)], 1) + ctr
                    drawn.append(self._add(scr, grey * 0.9, 0.9, t, t + 0.5))
                    t += 0.6
                if r < 0.85:                      # 지운다
                    e = rng.uniform(0.5, 1.1)
                    for it in drawn:
                        it['e0'], it['e1'] = t, t + e
                    t += e + rng.uniform(0.2, 0.6)
                else:                             # 희미하게 남겨 둔다 (형상이 드러날 때 함께 지운다)
                    for it in drawn:
                        it['ghost'] = (t, t + 2.0)
                        it['e0'], it['e1'] = rev[0] - 1.0, rev[0]
                i += 1
            t = max(t, t_stop)
            # ② 마침내 — 형상을 사람이 그은 순서대로 그려 낸다 (멈칫 · 틀렸다 고치기 포함), 드러나는 시각에 끝나게
            t0 = t
            current = self._draw_form(target, t, speed * 1.4)
            for it, (p, w, kind) in zip(current, target['items']):
                it['home'] = _resample(p)
            t = self._squeeze(t0, max(it['d1'] for it in current), rev[0])
            self.stage_t.append((t0, 0))
        else:
            # 앞 장면의 마지막 형상에서 시작 → 조각으로 풀렸다가 이 장면의 첫 형상으로 모인다
            for k, (p, w, kind) in enumerate(prev['items']):
                current.append(self._add(p, prev['cols'][k], w, -2.0, -1.0))
            self.stage_t.append((t, -1))
            current, t = self._drift(current, target, t, rev[0])
            self.stage_t.append((t, 0))
        # ③ 이야기를 따라 — 다음 오브제가 나오는 자리까지 조각으로 풀렸다가 다음 형상으로 모인다
        for j in range(1, n):
            hold_end = max(t + 3.0, rev[j - 1] + (rev[j] - rev[j - 1]) * 0.35)
            t = self._vary_until(current, t, hold_end, self.stages[j - 1])
            self.stage_t.append((hold_end, j))
            current, t = self._drift(current, self.stages[j], hold_end, rev[j])
        self.finale_t = t if end - t > 15.0 else None   # 마지막 형상 뒤 오래 남으면 끝까지 살아 있게
        self._vary_until(current, t, end, self.stages[-1], strong=self.finale_t is not None)

    def _drift(self, current, form, t, t_reveal):
        """지금 형상 → 조각(알아보기 어려운 상태) → 다음 형상이 t_reveal 에 드러난다"""
        rng, speed = self.rng, CHILD_SPEED.get(self.S.act, 0.55) * 1.6
        items = form['items']
        span = max(4.0, t_reveal - t)
        t_frag = t + span * 0.40      # 이때까지 조각으로 풀림
        t_gather = t + span * 0.62    # 이때부터 제자리를 찾아 모임
        new = []
        n_pair = min(len(current), len(items))
        for old in current[n_pair:]:  # 남는 옛 획은 조각으로 흩어지며 지워진다
            a = t + rng.uniform(0, span * 0.3)
            base = self._pts_at(old, a)
            old['e0'], old['e1'] = a, a
            fr = self._add(base, old['col'], old['w'], a - 1e-3, a, m0=a, m1=a + span * 0.3, pts2=_resample(self._frag(base, 0.8)))
            fr['e0'], fr['e1'] = a + span * 0.3, a + span * 0.3 + rng.uniform(0.6, 1.0)
        for k in range(len(items)):
            p, w, kind = items[k]
            col = form['cols'][k]
            mid = _resample(self._frag(p, rng.uniform(0.55, 0.9)))   # 알아보기 어려운 조각 상태
            a = t + rng.uniform(0, span * 0.15)
            if k < n_pair:                               # 옛 획이 조각으로 풀렸다가 → 새 형상의 획으로
                old = current[k]
                base = self._pts_at(old, a)
                w_ = rng.uniform(0.3, 0.7)                # 중간은 옛 형상과 새 형상이 섞인 잡종
                mid = _resample(self._frag(_match(base, p) * (1 - w_) + _resample(p) * w_, rng.uniform(0.35, 0.7)))
                old['e0'], old['e1'] = a, a
                c0 = old['col2'] if old.get('col2') is not None else old['col']
                f1 = self._add(base, c0, w, a - 1e-3, a, m0=a, m1=t_frag + rng.uniform(-1, 1), pts2=mid, col2=c0 * 0.5 + col * 0.5)
            else:                                        # 새 획은 조각으로 먼저 그어진다
                d = self._dur(mid, speed)
                a = t + rng.uniform(span * 0.1, span * 0.45)
                f1 = self._add(mid, col * 0.7 + 0.3, w, a, a + d)
            b = t_gather + rng.uniform(0, span * 0.2)
            f1['e0'], f1['e1'] = b, b
            f2 = self._add(mid, f1.get('col2') if f1.get('col2') is not None else f1['col'], w, b - 1e-3, b,
                           m0=b, m1=min(t_reveal, b + rng.uniform(1.5, 3.0)), pts2=_resample(p), col2=col)
            f2['home'] = _resample(p)
            new.append(f2)
        return new, max(t_reveal, max(it['m1'] for it in new))

    def _vary_until(self, current, t, t_until, form=None, strong=False):
        """머무는 동안에도 계속 변한다 — 고쳐 그렸다 되돌리기 · 되돌리지 않는 변이 · 다른 갈래의 획이 자라남 · 획 하나를 놓아 버림"""
        rng = self.rng
        form = form or (self.stages[-1] if self.stages else {})
        p_grow, p_lose, p_keep = (0.3, 0.42, 0.4) if strong else (0.15, 0.25, 0.3)
        amp_lo, amp_hi = (0.1, 0.22) if strong else (0.06, 0.14)
        while current and t + 5.0 < t_until:
            tv = t + (rng.uniform(1.2, 3.0) if strong else rng.uniform(2.0, 4.5))
            r = rng.random()
            if self.mode == 'doodle' and r < p_grow and form.get('alts') and len(current) < (14 if strong else 12):   # 자라남
                alt = form['alts'][int(rng.integers(len(form['alts'])))]
                p = _resample(self._frag(_resample(alt[int(rng.integers(len(alt)))]), 0.15))
                d = self._dur(p, CHILD_SPEED.get(self.S.act, 0.55) * 1.4)
                if tv + d > t_until:
                    break
                col = current[0]['col2'] if current[0].get('col2') is not None else current[0]['col']
                g_ = self._add(p, col * 0.85 + self.hue * 0.15, 0.8, tv, tv + d)
                g_['grown'] = True
                current.append(g_)
                t = tv + d
                continue
            grown = [i for i, c in enumerate(current) if c.get('grown')]
            if self.mode == 'doodle' and r < p_lose and grown:                                    # 자라난 획을 놓아 버림 (점으로 흩어짐)
                k = grown[int(rng.integers(len(grown)))]
                old = current.pop(k)
                e = rng.uniform(0.8, 1.4)
                if old.get('m1') is not None and old['m1'] > tv:
                    tv = old['m1']
                old['e0'], old['e1'] = tv, tv + e
                t = tv + e
                continue
            k = int(rng.integers(len(current)))
            old = current[k]
            base = old['pts2'] if old.get('pts2') is not None else old['pts']
            col = old['col2'] if old.get('col2') is not None else old['col']
            home = old.get('home')
            if self.mode == 'doodle':
                var = self._frag(base, rng.uniform(amp_lo, amp_hi))
                if home is not None:   # 원래 형상 쪽으로 조금 당긴다 — 변해도 무엇인지는 알아볼 수 있게
                    var = _match(var, home) * 0.65 + home * 0.35
            else:
                prim, _ = _primitive(rng)
                rot, sc_ = rng.uniform(-0.25, 0.25), rng.uniform(0.9, 1.15)
                c_, s_ = math.cos(rot), math.sin(rot)
                var = _blend(prim, base, rng.uniform(0.6, 0.8)) @ np.array([[c_, s_], [-s_, c_]], np.float32) * sc_
            d, hold = rng.uniform(1.5, 2.5), rng.uniform(0.6, 1.6)
            if tv + 2 * d + hold > t_until:
                break
            old['e0'], old['e1'] = tv, tv
            a_ = self._add(base, col, old['w'], tv - 1e-3, tv, m0=tv, m1=tv + d, pts2=_resample(var))
            a_['home'], a_['grown'] = home, old.get('grown')
            if self.mode == 'doodle' and rng.random() < p_keep:   # 되돌리지 않는 변이 — 형상이 조금씩 다른 것으로 진화한다
                current[k] = a_
                t = tv + d
                continue
            a_['e0'], a_['e1'] = tv + d + hold, tv + d + hold
            b_ = self._add(var, col, old['w'], tv + d + hold - 1e-3, tv + d + hold, m0=tv + d + hold,
                           m1=tv + 2 * d + hold, pts2=_resample(base))
            b_['home'], b_['grown'] = home, old.get('grown')
            current[k] = b_
            t = tv + 2 * d + hold
        return t

    def _draw_form(self, form, t, speed):
        rng = self.rng
        out = []
        for k, (p, w, kind) in enumerate(form['items']):
            col = form['cols'][k]
            d = self._dur(p, speed)
            t += rng.uniform(0.2, 0.6)
            if rng.random() < CHILD_RETRY:  # 비뚤게 그었다가 지우고 다시
                rot, sc_ = rng.uniform(-0.3, 0.3), rng.uniform(1.08, 1.25)
                c_, s_ = math.cos(rot), math.sin(rot)
                wp = p @ np.array([[c_, s_], [-s_, c_]], np.float32) * sc_ + rng.uniform(-0.06, 0.06, 2).astype(np.float32)
                part = rng.uniform(0.4, 0.75)
                bad = self._add(wp[:max(2, int(ONE_N * part))], col * 0.85, w, t, t + d * part)
                t += d * part + rng.uniform(0.4, 0.9)
                bad['e0'], bad['e1'] = t, t + max(0.4, d * part * 0.5)
                t = bad['e1'] + 0.3
            if rng.random() < CHILD_HESITATE:  # 멈칫 — 두 번에 나눠 긋는다 (펜이 그 자리에서 머뭇)
                f1 = rng.uniform(0.3, 0.7)
                it = self._add(p, col, w, t, t + d, pause=(f1, rng.uniform(0.4, 0.9)))
                t += d + it['pause'][1]
                it['d1'] = t
            else:
                it = self._add(p, col, w, t, t + d)
                t += d
            out.append(it)
        return out

    def _transform(self, current, form, t, speed):
        """지금 모양 → 다음 모양 : 남는 옛 획을 먼저 지우고, 짝지은 획은 펜이 따라가며 휘어 바꾸고, 모자란 획은 새로 긋는다"""
        rng = self.rng
        items = form['items']
        n_pair = min(len(current), len(items))
        for old in current[n_pair:]:                # 남는 옛 획 정리 (한 번에 겹쳐 보이지 않게)
            e = rng.uniform(0.5, 0.9)
            old['e0'], old['e1'] = t, t + e
            t += e * 0.6
        new = []
        for k in range(n_pair):
            old = current[k]
            p, w, kind = items[k]
            col = form['cols'][k]
            t += rng.uniform(0.15, 0.4)
            if k == 0 or rng.random() < 0.8:        # 휘어 바꾸기 — 몸통은 늘 이 방식 (화면이 비지 않게)
                d = self._dur(p, speed) * rng.uniform(1.0, 1.5)
                old_pts = self._pts_at(old, t)
                old['e0'], old['e1'] = t, t
                it = self._add(old_pts, old['col'], w, t - 1e-3, t, m0=t, m1=t + d, pts2=_resample(p), col2=col)
                new.append(it)
                t += d
            else:                                     # 이 획만 지우고 다시 긋기
                e = rng.uniform(0.5, 1.0)
                old['e0'], old['e1'] = t, t + e
                t += e + rng.uniform(0.15, 0.4)
                d = self._dur(p, speed)
                new.append(self._add(p, col, w, t, t + d))
                t += d
        for k in range(n_pair, len(items)):          # 모자란 획 새로 긋기
            p, w, kind = items[k]
            t += rng.uniform(0.2, 0.5)
            d = self._dur(p, speed)
            new.append(self._add(p, form['cols'][k], w, t, t + d))
            t += d
        return new, t

    # ── 진화 모드 ───────────────────────────────────────
    def _target_points(self, entry):
        """목표 선화 → 점들 (단위 상자 · 획 순서 · 역할)"""
        P, sid, role = [], [], []
        for k, st in enumerate(entry.get('strokes') or []):
            p = (np.asarray(st['points'], np.float32) - 500.0) / 1000.0 * 1.6   # 크기 — 화면 높이의 약 40%
            L = float(np.hypot(*(p[1:] - p[:-1]).T).sum()) if len(p) > 1 else 0
            n = max(2, int(L / EVO_STEP))
            q = _resample(p, n)
            P.append(q)
            sid += [k] * len(q)
            role += [st['role']] * len(q)
        P = np.concatenate(P) if P else np.zeros((1, 2), np.float32)
        return P.astype(np.float32), np.array(sid), np.array(role)

    def _init_evolve(self, target_scene, prev_target, seed):
        S, T = self.S, self.scene_sec
        self.mode = 'evolve'
        self.ev_rng = np.random.default_rng(seed + 303)
        st_list = []
        for j, e in enumerate(target_scene):
            if not e.get('strokes'):
                continue
            beh = {k: (v[j] if j < len(v) else False) for k, v in S.beh_arr.items()}
            P, sid, role = self._target_points(e)
            st_list.append(dict(P=P, sid=sid, role=role, beh=beh, name=e.get('name', ''),
                                category=e.get('subject', ''), reveal=float(e.get('reveal', 0.5)),
                                col=self.pal[j % len(self.pal)], acc=self.pal[(j + 3) % len(self.pal)]))
        st_list.sort(key=lambda f: f['reveal'])
        self.stages = st_list
        n = len(st_list)
        end = T * (0.93 if self.is_last else 0.97)
        lo = (0.30 if prev_target is None else 0.18) * T
        margin = min(6.0, 0.08 * T)
        hi = max(lo + 0.5, end - margin)
        rev = [lo + (hi - lo) * min(1.0, max(0.0, s_['reveal'])) for s_ in st_list]
        gap = min(14.0, (hi - lo) / max(n, 1))
        for j in range(n):
            rev[j] = max(rev[j], lo if j == 0 else rev[j - 1] + gap)
        if rev[-1] > hi:
            rev = [lo + (r - lo) * (hi - lo) / max(rev[-1] - lo, 1e-3) for r in rev]
        if S.rev is not None:   # 반전(무리가 터지는 순간) 앞뒤 5초에는 형상이 드러나지 않게 — 반전 6초 뒤로 민다
            rt = S.rev * T
            for j in range(n):
                if abs(rev[j] - rt) < 5.0:
                    before = rt - 6.0
                    prev_r = rev[j - 1] if j > 0 else lo - 99
                    nxt = rev[j + 1] if j + 1 < n else hi + 99
                    if before >= prev_r + 0.6 * gap:          # 앞 형상과 충분히 떨어지면 반전 앞으로
                        rev[j] = before
                    else:                                     # 아니면 반전 뒤로 · 뒤 형상들도 간격을 두고 밀어낸다
                        rev[j] = min(hi, rt + 6.0)
                        for k in range(j + 1, n):
                            rev[k] = min(hi, max(rev[k], rev[k - 1] + 0.6 * gap))
                if j > 0 and rev[j] < rev[j - 1] + 4.0:
                    rev[j] = min(hi, rev[j - 1] + 4.0)
        self.reveal_t = rev
        # 한 형상을 향해 진화하기 시작하는 때 = 앞 형상이 드러난 뒤 조금 머문 다음
        self.evo_start = [0.0] + [rev[j - 1] + (rev[j] - rev[j - 1]) * 0.35 for j in range(1, n)]
        self.stage_t = [(self.evo_start[j], j) for j in range(n)]
        self.finale_t = rev[-1] if end - rev[-1] > 15.0 else None
        N = EVO_N
        self.N = N
        rng = self.ev_rng
        self.from_prev = prev_target is not None and bool(prev_target.get('strokes'))
        if self.from_prev:   # 앞 장면의 마지막 형상에서 시작
            P0, _, _ = self._target_points(prev_target)
            self.pos = P0[np.linspace(0, len(P0) - 1, N).astype(int)] + rng.normal(0, 0.01, (N, 2)).astype(np.float32)
        else:                                                       # 랜덤 위치의 점에서 시작
            r = np.sqrt(rng.random(N)) * 0.62
            a = rng.random(N) * 2 * np.pi
            self.pos = np.stack([np.cos(a) * r * 1.35, np.sin(a) * r], 1).astype(np.float32)
        self.ev_t = 0.0
        self.ev_stage = -1
        self.ga_log = []   # (시각, 목표 번호, 평균 적합도, 최고 적합도, 자리 잡은 비율)
        self._assign(0)
        self.burst_at = []
        for j in range(n):   # 형상이 드러난 뒤 — 몇 세대마다 일부 개체가 크게 변이했다가 다시 진화 (멈추지 않는 진화)
            t_ = rev[j] + rng.uniform(5, 9)
            t_end = (self.evo_start[j + 1] if j + 1 < n else end)
            while t_ < t_end - 2:
                self.burst_at.append(t_)
                t_ += rng.uniform(6, 11) * (0.7 if (self.finale_t and t_ > self.finale_t) else 1.0)

    def _assign(self, j):
        """개체 i 가 향할 목표 점 — 선 순서를 지켜 나눠 준다 (이웃 개체 = 같은 선의 이웃 점)"""
        st = self.stages[j]
        M = len(st['P'])
        self.tgt_idx = np.minimum((np.arange(self.N) * M / self.N).astype(int), M - 1)
        self.ev_stage = j

    def _goal(self, t, s_):
        """지금의 목표 점들 — 드러난 뒤에는 꿈의 변형으로 목표 자체가 흐트러진다 (정적인 물체로 머물지 않게)"""
        st = self.stages[self.ev_stage]
        G = st['P'][self.tgt_idx]
        if s_ > 0:
            sid = st['sid'][self.tgt_idx]
            out = G.copy()
            for k in np.unique(sid):
                m = sid == k
                out[m] = self._dream(G[m], {'uid': int(k) * 7 + self.ev_stage * 131}, t, s_, st['beh'])
            G = out
        return G

    def _evolve_to(self, t):
        """세대를 t 까지 진행 — 변이(돌연변이) → 목표에 더 가까우면 살아남음(선택) + 목표 쪽으로 이끌림"""
        if t < self.ev_t - 1e-6:
            return
        rng = self.ev_rng
        while self.ev_t + EVO_GEN <= t + 1e-6:
            tg = self.ev_t + EVO_GEN
            j = max([k for k, s0 in enumerate(self.evo_start) if s0 <= tg] or [0])
            if j != self.ev_stage:
                self._assign(j)
                self.pos += rng.normal(0, 0.015, self.pos.shape).astype(np.float32)  # 새 목표로 — 무리가 살짝 흔들린다
            r = self.reveal_t[j]
            s0 = self.evo_start[j]
            prog = float(np.clip((tg - s0) / max(r - s0, 1e-3), 0, 1))   # 목표에 다가가는 진행 (드러나는 때에 1)
            G = self._goal(tg, self.dream_strength(tg))
            sigma = 0.05 * (1 - prog) ** 1.2 + 0.004                        # 변이 크기 — 처음엔 크게, 다가갈수록 작게
            cand = self.pos + rng.normal(0, sigma, self.pos.shape).astype(np.float32)
            d_old = np.hypot(*(self.pos - G).T)
            d_new = np.hypot(*(cand - G).T)
            first = (j == 0 and not self.from_prev)                           # 맨 처음(랜덤 점)만 오래 떠돈다
            if first:
                p_sel = 0.04 + 0.96 * prog ** 3                              # 선택압 — 처음엔 약해 무리가 정처 없이 떠돌다가 점점 강해진다
                explore = 0.45 * (1 - prog) ** 2 + 0.03                      # 엉뚱한 변이도 살아남는 비율
            else:                                                            # 형상 → 형상: 섞이며 넘어간다 (화면이 비지 않게)
                p_sel = 0.1 + 0.9 * prog ** 2
                explore = 0.25 * (1 - prog) ** 2 + 0.02
            keep = ((d_new < d_old) & (rng.random(self.N) < p_sel)) | (rng.random(self.N) < explore)
            fit = -d_old                                                    # 적합도 (클수록 좋음)
            order = np.argsort(-fit)
            elite = order[:int(self.N * GA_ELITE)]
            keep[elite] = False                                             # 엘리트 보존 — 가장 나은 개체는 변이시키지 않는다
            self.pos = np.where(keep[:, None], cand, self.pos)
            # 도태 · 교차 — 하위 개체를, 같은 선 위 이웃 자리의 상위 개체 둘을 섞은 자식으로 바꾼다
            n_rep = max(1, int(self.N * GA_REPLACE * (0.3 + 0.7 * prog)))
            worst = order[-n_rep:]
            rank = np.empty(self.N, np.int64)
            rank[order] = np.arange(self.N)
            for w_ in worst:
                cand_p = np.clip(w_ + rng.integers(-6, 7, 4), 0, self.N - 1)        # 이웃 자리 4개 중
                p1, p2 = sorted(cand_p, key=lambda c: rank[c])[:2]                    # 순위가 높은 둘이 부모 (토너먼트)
                a = rng.random()
                child = self.pos[p1] * a + self.pos[p2] * (1 - a)                     # 교차 (산술 교차)
                off = G[w_] - (G[p1] * a + G[p2] * (1 - a))                           # 부모 자리 → 자기 자리로 옮겨 붙임
                self.pos[w_] = child + off * (0.2 + 0.8 * prog ** 2) + rng.normal(0, sigma * 0.5, 2)   # 자식 변이 (처음엔 부모 곁에)
            if int(tg * 2) != int(self.ev_t * 2):                               # 0.5초마다 기록 (발표 그래프용)
                self.ga_log.append((round(tg, 2), j, round(float(np.mean(-d_old)), 4), round(float(-d_old.min()), 4),
                                    round(float(np.mean(d_old < 0.035)), 3)))
            pull = (0.0005 + 0.08 * prog ** 3) if first else (0.0008 + 0.08 * prog ** 3)   # 드러나는 때가 가까워질수록 목표에 끌림
            self.pos += (G - self.pos) * pull
            rr_ = np.hypot(*self.pos.T)
            far_ = rr_ > 0.95                                                # 화면 밖으로 흩어지지 않게
            self.pos[far_] *= (0.95 / rr_[far_])[:, None]
            for b in self.burst_at:
                if self.ev_t < b <= tg:   # 큰 변이 — 일부 개체가 흩어졌다가 다시 진화
                    m = rng.random(self.N) < 0.22
                    self.pos[m] += rng.normal(0, 0.12, (int(m.sum()), 2)).astype(np.float32)
            self.ev_t = tg

    def _render_evolve(self, t, place, stroke, layer, mask, fade, thick, dots=None):
        """점(개체)과, 목표 가까이 모인 이웃 개체끼리 이어진 선"""
        H, W = self.S.H, self.S.W
        self._evolve_to(t)
        st = self.stages[self.ev_stage]
        G = self._goal(t, self.dream_strength(t))
        d = np.hypot(*(self.pos - G).T)
        P = place(self.pos)
        sid = st['sid'][self.tgt_idx]
        role = st['role'][self.tgt_idx]
        w_role = {'main': 1.0, 'detail': 0.85, 'accent': 0.55, 'grid': 0.4}
        a_role = {'main': 1.0, 'detail': 1.0, 'accent': 0.7, 'grid': 0.45}
        near = d < 0.035
        # 같은 선의 이웃 개체가 둘 다 목표 가까이 오면 그 사이를 잇는다 → 선이 조각조각 생겨나 형상이 된다
        brk = np.where((sid[1:] != sid[:-1]) | ~near[1:] | ~near[:-1])[0] + 1
        for seg in np.split(np.arange(self.N), brk):
            if len(seg) < 2 or not near[seg[0]]:
                continue
            r_ = role[seg[0]]
            C = self._cols
            col = C['same'] if r_ == 'main' else (C['near'] if r_ in ('detail', 'grid') else C['comp'])
            stroke(P[seg], col, w_role.get(r_, 0.6), a_role.get(r_, 0.6) * fade, raw=True)
            if r_ == 'main':   # 어긋난 색 그림자 선 (예시 선화처럼) — 반대색은 덧그림에만
                stroke(P[seg] + [thick * 0.9, thick * 0.6], C['comp'], 0.4, 0.35 * fade, raw=True)
        # 형상 둘레의 동심원 · 작은 원 · 점 — 형상이 갖춰질수록 또렷해지고 천천히 돈다 (교수님 예시 선화처럼 · 은은하게)
        if EVO_RINGS > 0:
            j = self.ev_stage
            r_ = self.reveal_t[j]
            show = float(smoothstep(r_ - 4.0, r_ + 2.0, t)) * EVO_RINGS * fade
            if show > 0.01:
                c0 = place(np.zeros((1, 2), np.float32))[0]
                unit = float(np.hypot(*(place(np.array([[0.5, 0.0]], np.float32))[0] - c0))) * 2
                grng = np.random.default_rng(1000 + j)
                for k, rad in enumerate((0.42, 0.58, 0.74)):
                    R = rad * unit
                    n_dash = int(40 + 30 * k)
                    ph = t * (0.05 + 0.03 * k) * (1 if k % 2 == 0 else -1)
                    for q in range(n_dash):
                        a0 = ph + 2 * np.pi * q / n_dash
                        a1 = a0 + np.pi / n_dash
                        pts = np.array([[c0[0] + R * np.cos(a), c0[1] + R * np.sin(a)] for a in np.linspace(a0, a1, 3)])
                        stroke(pts, self._cols['comp'] if k % 2 else self._cols['near'], 0.35, show * (0.9 - 0.2 * k), raw=True)
                for q in range(9):   # 작은 원 · 점
                    a = grng.uniform(0, 2 * np.pi) + t * 0.02
                    R = grng.uniform(0.45, 0.85) * unit
                    x, y = c0[0] + R * np.cos(a), c0[1] + R * np.sin(a)
                    if q % 3 == 0:
                        cc = np.array([[x + 0.025 * unit * np.cos(b), y + 0.025 * unit * np.sin(b)] for b in np.linspace(0, 2 * np.pi, 16)])
                        stroke(cc, self._cols['comp'], 0.35, show, raw=True)
                    elif 0 <= x < W and 0 <= y < H:
                        cv2.circle(layer, (int(x), int(y)), max(1, int(H / 400)), (self._cols['near'] * show).tolist(), -1, cv2.LINE_AA)
        # 아직 자리를 못 찾은 개체 = 떠도는 점 · 가까운 이웃끼리는 가는 실로 이어진다 (무리가 살아 있는 게 보이게)
        far = ~near
        # 맨 처음 랜덤 점 단계 — 점을 더 크고 밝게, 실도 더 길게 (교수님 제안의 출발점이 또렷이 보이게)
        early = 0.0
        if self.ev_stage == 0 and not self.from_prev:
            early = 1.0 - float(smoothstep(self.reveal_t[0] - 8.0, self.reveal_t[0], t))
        gap = np.hypot(*(self.pos[1:] - self.pos[:-1]).T)
        web = (sid[1:] == sid[:-1]) & (gap < 0.06 + 0.04 * early) & (far[1:] | far[:-1])
        brk2 = np.where(~web)[0] + 1
        for seg in np.split(np.arange(self.N), brk2):
            if len(seg) >= 3 and web[min(seg[0], len(web) - 1)]:
                stroke(P[seg], self._cols['near'], 0.3, (0.5 + 0.2 * early) * fade, raw=True)
        if dots is not None:
            px = H * 0.0045 * (1 + 0.7 * early)   # 점 지름(화소) — 1080p 에서 약 5px, 처음엔 약 8px
            dots(P[far], self._cols['same'], px / max(thick, 1), min(1.0, 0.85 + 0.15 * early) * fade, raw=True)

    def dream_strength(self, t):
        """지금 꿈의 변형 세기 (0 = 그 물체 그대로)"""
        if self.mode not in ('doodle', 'evolve') or not getattr(self, 'reveal_t', None):
            return 0.0
        if self.mode == 'evolve':   # 진화 중인 형상은 흐트러뜨리지 않는다 — 드러나는 순간 그 모습으로 모이고, 그 뒤에 꿈처럼 흐트러진다
            j = max([k for k, s0 in enumerate(self.evo_start) if s0 <= t] or [0])
            if t < self.reveal_t[j]:
                return 0.0
            r = self.reveal_t[j]
        else:
            past = [r for r in self.reveal_t if r <= t]
            if not past:
                return 0.0
            r = past[-1]
        ramp = float(smoothstep(r + 1.5, r + 6.0, t))
        wave = 0.7 + 0.3 * math.sin(2 * math.pi * t / 9.5)
        fin = 1.25 if (self.finale_t is not None and t > self.finale_t + 6) else 1.0
        return DREAM_MAX.get(self.S.act, 0.7) * ramp * wave * fin

    def _dream(self, pts, it, t, s, beh):
        """획 하나를 꿈의 논리로 흐트러뜨린다 — 따로 떠다님 · 돎 · 늘었다 줄음 · 선의 일렁임 + 스토리 법칙의 방향"""
        u_ = it.get('uid', 0)
        ph = [(u_ * k * 0.618) % (2 * np.pi) for k in (1, 2, 3, 5, 7)]
        c = pts.mean(0)
        rot = s * 0.6 * math.sin(t * 0.37 + ph[0])
        if beh.get('rotate'):
            rot += s * 0.25 * t
        sc_x = 1 + s * 0.25 * math.sin(t * 0.29 + ph[1])
        sc_y = 1 + s * 0.25 * math.sin(t * 0.31 + ph[2])
        if beh.get('stretch'):
            sc_y += s * 0.35 * (0.6 + 0.4 * math.sin(t * 0.2 + ph[3]))
        d = np.array([math.sin(t * 0.23 + ph[3]), math.cos(t * 0.19 + ph[4])], np.float32) * (s * 0.18)
        if beh.get('float') or beh.get('weightless'):
            d[1] -= s * 0.12 * (0.6 + 0.4 * math.sin(t * 0.4 + ph[0]))   # 획들이 제각각 위로 떠오른다
        if beh.get('heavy'):
            d[1] += s * 0.1
        cr, sr = math.cos(rot), math.sin(rot)
        q = (pts - c) * [sc_x, sc_y]
        q = q @ np.array([[cr, sr], [-sr, cr]], np.float32) + c + d
        f = 2.0 if beh.get('flutter') else 1.0
        warp = np.stack([np.sin(q[:, 1] * 3.1 * f + t * 0.7 + ph[1]), np.cos(q[:, 0] * 2.7 * f + t * 0.6 + ph[2])], 1)
        return (q + warp * (s * 0.05)).astype(np.float32)

    def _pts_at(self, it, t):
        if it.get('pts2') is not None and it['m0'] is not None:
            m = float(np.clip((t - it['m0']) / max(it['m1'] - it['m0'], 1e-6), 0, 1))
            m = m * m * (3 - 2 * m)
            if it.get('_al') is None:
                it['_al'] = _match(it['pts'], it['pts2'])  # 점 짝을 맞춘 옛 모양
            return it['_al'] * (1 - m) + it['pts2'] * m
        return it['pts']

    # ── 지금 모양의 움직임 (스토리 법칙) ─────────────────────
    def _stage_at(self, t):
        cur = 0
        for t0, j in self.stage_t:
            if t >= t0 and j >= 0:
                cur = j
        return self.stages[min(cur, len(self.stages) - 1)] if self.stages else {'beh': {}}

    def _motion(self, t, u):
        S = self.S
        beh = self._stage_at(t)['beh']
        dx = dy = rot = 0.0
        sx = sy = 1.0
        H, W = S.H, S.W
        if beh.get('float') or beh.get('weightless'):
            dy -= H * 0.035 * math.sin(2 * math.pi * t / 6.5) + (H * 0.04 * u if beh.get('weightless') else 0)
        if beh.get('heavy'):
            dy += H * 0.08 * u
            sy *= 1 - 0.12 * u
        if beh.get('glide'):
            dx += W * 0.06 * math.sin(2 * math.pi * t / 14)
        if beh.get('rotate'):
            rot += 0.35 * math.sin(2 * math.pi * t / 11)
        if beh.get('stretch'):
            sy *= 1 + 0.35 * u
        if beh.get('recede'):
            k_ = 0.2 if self.mode == 'doodle' else 0.35
            sx *= 1 - k_ * u
            sy *= 1 - k_ * u
        if beh.get('flutter'):
            rot += 0.06 * math.sin(2 * math.pi * t / 1.3)
        per = 8.0
        m = 1 + SIZE_BREATH.get(S.act, 0.12) * math.sin(2 * math.pi * t / per)
        if getattr(self, 'finale_t', None) is not None:
            m *= 1 + (0.3 if self.is_last else 0.12) * float(smoothstep(self.finale_t, self.scene_sec * 0.9, t))
        if S.rev is not None:
            lead = 6.0 / self.scene_sec
            if S.rev - lead <= u < S.rev:
                m *= 1 + 0.2 * float(smoothstep(S.rev - lead, S.rev, u))
        return dx, dy, rot, sx * m, sy * m, beh

    # ── 그리기 ───────────────────────────────────────────
    def render(self, frame, u, t, composite):
        S = self.S
        W, H = S.W, S.H
        flip, pull, cmix = S.rev_phase(u)
        burst = (1 - min(1.0, pull)) if flip else 0.0
        tq = math.floor(t * 8) / 8
        thick = max(2, int(H * 0.0095 * min(1.2, self.L['thick']) * (1.2 if self.mode == 'doodle' else 1.0)))
        layer = np.zeros((H, W, 3), np.float32)
        mask = np.zeros((H, W), np.float32)
        tint = S.rev_tint
        dx, dy, rot, sx, sy, beh = self._motion(t, u)
        if flip:
            rot += math.pi
        # 배경과 동떨어지지 않게 — 오브제 둘레의 실제 배경 색을 읽어, 같은 색 계열의 밝고 맑은 색으로 선을 물들인다
        bgc = None
        if composite:
            r0, r1 = int(H * 0.15), int(H * 0.85)
            c0, c1 = int(W * 0.25), int(W * 0.75)
            patch = cv2.resize(frame[r0:r1, c0:c1], (32, 24), interpolation=cv2.INTER_AREA).reshape(-1, 3)
            wgt = patch.max(1) + 1e-3                           # 밝은 점(배경 파티클)의 색을 더 믿는다
            m = (patch * wgt[:, None]).sum(0) / wgt.sum()
            import colorsys
            hh, ss, vv = colorsys.rgb_to_hsv(*[float(x) for x in np.clip(m, 0, 1)])
            hsv = cv2.cvtColor((np.clip(patch.reshape(24, 32, 3), 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).reshape(-1, 3).astype(np.float32)
            ang = hsv[:, 0] / 180.0 * 2 * np.pi
            wt = (hsv[:, 1] / 255.0) * (hsv[:, 2] / 255.0)                  # 채도 × 밝기 — 흰 반짝임 · 어둠은 거의 안 센다
            cs, sn = float((np.cos(ang) * wt).sum()), float((np.sin(ang) * wt).sum())
            strength = math.hypot(cs, sn) / max(len(wt), 1)
            if strength > 0.06:
                hh = (math.atan2(sn, cs) / (2 * np.pi)) % 1.0
            else:                                                            # 거의 무채색이면 색표의 장면 주색
                hh = EMO_BG_HUE.get(S.emo_label, 220) / 360.0
            ph = getattr(self, '_bghue', None)   # 배경 주색(색상) — 원 위에서 천천히 따라간다
            if ph is None or abs(t - getattr(self, '_bgc_t', -9)) > 0.5:
                self._bghue = hh
            else:
                dh = ((hh - ph + 0.5) % 1.0) - 0.5
                self._bghue = (ph + dh * ONE_BG_EMA) % 1.0
            ref = np.array(colorsys.hsv_to_rgb(hh, min(0.8, ss * 1.8 + 0.2), 0.95), np.float32)
            b_ = float(cv2.resize(frame[r0:r1, c0:c1], (32, 24), interpolation=cv2.INTER_AREA).mean())
            y_goal = 0.74  # 선은 늘 배경 색 계열의 밝은 색 (밝은 배경에서는 아래 '잔잔한 받침'이 대비를 만든다)
            self._bright = b_
            prev_y = getattr(self, '_ygoal', None)
            self._ygoal = y_goal if prev_y is None or abs(t - getattr(self, '_bgc_t', -9)) > 0.5 else prev_y * (1 - ONE_BG_EMA) + y_goal * ONE_BG_EMA
            prev = getattr(self, '_bgc', None)
            if prev is None or abs(t - getattr(self, '_bgc_t', -9)) > 0.5:
                self._bgc = ref
            else:
                self._bgc = prev * (1 - ONE_BG_EMA) + ref * ONE_BG_EMA
            self._bgc_t = t
            bgc = self._bgc
        size = 0.46 * H * ONE_ACT_SIZE.get(S.act, 1.0)
        size *= min(1.0, 0.78 * H / (size * max(sx, sy, 1e-3)))     # 커져도 화면 안에 들어오게
        cx, cy = W * 0.5 + dx, H * 0.5 + float(np.clip(dy, -0.1 * H, 0.1 * H))
        c_, s_ = math.cos(rot), math.sin(rot)
        fade = 1.0
        if self.is_last:  # 마지막 장면 끝에서만 부드럽게 사라진다
            fade = 1.0 - float(smoothstep(self.scene_sec - 2.5, self.scene_sec - 0.2, t))
        amp = 0.0 if beh.get('still') else 0.006

        def place(p):
            p = _wobble(p, amp, 1.7, tq) * size
            p = p * [sx, sy]
            q = np.stack([cx + p[:, 0] * c_ - p[:, 1] * s_, cy + p[:, 0] * s_ + p[:, 1] * c_], 1)
            if burst > 0:
                d = q - [cx, cy]
                q = q + d / (np.linalg.norm(d, axis=1, keepdims=True) + 1) * (H * 0.45 * burst)
            return q

        def to_lum(c, y):
            """색 계열은 두고 밝기(휘도)만 y 에 맞춘다"""
            yc = float(c @ np.array([0.2126, 0.7152, 0.0722], np.float32))
            if yc > y:
                return c * (y / max(yc, 1e-3))
            k = (y - yc) / max(1 - yc, 1e-3)
            return c + (1 - c) * k

        def stroke(P, col, w, alpha, raw=False):
            if len(P) < 2 or alpha <= 0.01:
                return
            if bgc is not None and not raw:
                col = to_lum(col * (1 - ONE_BG_MIX) + bgc * ONE_BG_MIX, self._ygoal)
            if cmix > 0:
                col = col * (1 - cmix) + tint * cmix
            Pi = P.astype(np.int32).reshape(-1, 1, 2)
            th = max(1, int(thick * w))
            cv2.polylines(layer, [Pi], False, (col * alpha).tolist(), th, cv2.LINE_AA)
            cv2.polylines(cov, [Pi], False, alpha, th, cv2.LINE_AA)        # 선이 덮는 자리 (짙은 선도 배경을 가린다)
            cv2.polylines(mask, [Pi], False, alpha, th + 6, cv2.LINE_AA)
            cv2.polylines(under, [Pi], False, alpha, th + max(4, thick), cv2.LINE_AA)  # 밝은 배경용 어두운 테두리

        under = np.zeros((H, W), np.float32)
        cov = np.zeros((H, W), np.float32)

        def dots(P, col, w, alpha, raw=False):
            """점 묶음 — 선과 같은 색 맞춤 · 덮개 · 테두리 (한 번에 그린다)"""
            if len(P) == 0 or alpha <= 0.01:
                return
            if bgc is not None and not raw:
                col = to_lum(col * (1 - ONE_BG_MIX) + bgc * ONE_BG_MIX, self._ygoal)
            if cmix > 0:
                col = col * (1 - cmix) + tint * cmix
            th = max(2, int(thick * w))
            segs = [np.array([[x, y], [x + 1, y]], np.int32).reshape(-1, 1, 2) for x, y in P.astype(int)]
            cv2.polylines(layer, segs, False, (col * alpha).tolist(), th, cv2.LINE_AA)
            cv2.polylines(cov, segs, False, alpha, th, cv2.LINE_AA)
            cv2.polylines(mask, segs, False, alpha * 0.7, th + 4, cv2.LINE_AA)
            cv2.polylines(under, segs, False, alpha, th + max(3, thick // 2), cv2.LINE_AA)

        pen = None
        ds = self.dream_strength(t)
        if self.mode == 'evolve':
            import colorsys
            if bgc is not None:
                base_h = self._bghue
                bright_bg = getattr(self, '_bright', 0.0) > 0.45
            else:   # 오브제만 렌더 — 색표의 장면 주색
                base_h = EMO_BG_HUE.get(S.emo_label, 220) / 360.0
                bright_bg = False
            y_ = COLOR_Y_ON_BRIGHT if bright_bg else COLOR_Y_ON_DARK
            near_h = (base_h + 30 / 360) % 1.0
            if 60 / 360 <= near_h <= 150 / 360:   # 누런 초록으로 가면 반대쪽으로
                near_h = (base_h - 30 / 360) % 1.0
            mk = lambda h: to_lum(np.array(colorsys.hsv_to_rgb(h, COLOR_SAT, 1.0), np.float32), y_)
            self._cols = {'same': mk(base_h), 'near': mk(near_h),
                          'comp': to_lum(np.array(colorsys.hsv_to_rgb((base_h + 0.5) % 1.0, COLOR_SAT * 0.9, 1.0), np.float32),
                                         y_ + (0.08 if bright_bg else -0.12))}   # 반대색도 밝기는 같은 쪽 — 덧그림이 윤곽보다 튀지 않게
            self._dark_lines = bright_bg
            self._render_evolve(t, place, stroke, layer, mask, fade, thick, dots)
        for it in self.inst:
            if t < it['d0']:
                continue
            pts = self._pts_at(it, t)
            if ds > 0:
                pts = self._dream(pts, it, t, ds, beh)
            col = it['col']
            if it.get('col2') is not None and it['m0'] is not None:
                m = float(np.clip((t - it['m0']) / max(it['m1'] - it['m0'], 1e-6), 0, 1))
                col = col * (1 - m) + it['col2'] * m
                if it['m0'] <= t < it['m1']:
                    pen = ('draw', place(pts[None, int((len(pts) - 1) * m)])[0])
            # 그리는 비율 (멈칫 구간 포함)
            if it['d1'] <= it['d0'] or t >= it['d1']:
                frac = 1.0
            else:
                frac = (t - it['d0']) / (it['d1'] - it['d0'])
                if it.get('pause'):
                    f1, pz = it['pause']
                    dd = it['d1'] - it['d0'] - pz
                    tt = t - it['d0']
                    frac = tt / dd if tt < dd * f1 else (f1 if tt < dd * f1 + pz else (tt - pz) / dd)
                frac = min(1.0, frac)
            if it['e0'] is not None and t >= it['e0']:
                if it['e1'] <= it['e0'] or t >= it['e1']:
                    continue
                ef = 1 - (t - it['e0']) / (it['e1'] - it['e0'])
                frac = min(frac, ef)
                n_ = max(2, int(len(pts) * frac))
                pen = ('erase', place(pts[n_ - 1:n_])[0])
            alpha = fade
            if it.get('ghost') is not None and t >= it['ghost'][0]:
                g0, g1 = it['ghost']
                alpha *= 1 - 0.8 * float(np.clip((t - g0) / (g1 - g0), 0, 1))
            if beh.get('flicker') and frac >= 1 and int(t / 1.4 + id(it) % 5) % 4 == 0:
                alpha *= 0.4
            n_ = max(2, int(math.ceil(len(pts) * frac)))
            P = place(pts[:n_])
            stroke(P, col, it['w'], alpha)
            if 0 < frac < 1 and (it['e0'] is None or t < it['e0']):
                pen = ('draw', P[-1])
        # 사람의 획이 지워질 때 기계의 점(배경 파티클 같은)으로 흩어져 잠시 남는다
        dust_r = max(1, int(round(H / 540)))
        for it in self.inst:
            e0, e1 = it['e0'], it['e1']
            if e0 is None or e1 - e0 < 0.05 or t < e0 or t > e1 + ONE_DUST:
                continue
            pts = it['pts2'] if it.get('pts2') is not None else it['pts']
            n_ = len(pts)
            idx = np.arange(0, n_, 3)
            t_pass = e0 + (1 - idx / max(n_ - 1, 1)) * (e1 - e0)       # 지우개가 그 점을 지난 시각
            age = t - t_pass
            ok = (age > 0) & (age < ONE_DUST)
            if not ok.any():
                continue
            idx, age = idx[ok], age[ok]
            P = place(pts[idx])
            hsh = (idx * 2654435761 + id(it)) % 1000 / 1000.0
            ang = hsh * 2 * np.pi
            sp = (0.02 + 0.03 * hsh) * H
            P = P + np.stack([np.cos(ang), np.sin(ang) - 0.6], 1) * (sp * age)[:, None]
            al = (1 - age / ONE_DUST) * fade
            col = (it['col'] * 0.5 + (bgc if bgc is not None else self.hue) * 0.5)  # 흩어진 점도 배경 색 계열로
            for (x, y), a_ in zip(P.astype(int), al):
                if 0 <= x < W and 0 <= y < H:
                    cv2.circle(layer, (int(x), int(y)), dust_r, (col * a_ * 0.9).tolist(), -1, cv2.LINE_AA)
        if pen is None:
            for a, b, pos in self.hover:
                if a <= t < b:
                    pen = ('draw', place((pos if pos is not None else np.zeros(2, np.float32))[None])[0]
                           + np.array([math.sin(t * 7) * 2, math.cos(t * 5) * 2]))
        if pen is not None and fade > 0.05:
            kind, p = pen
            x, y = int(p[0]), int(p[1])
            r = max(3, int(thick * 0.9))
            if kind == 'erase':
                cv2.circle(layer, (x, y), int(r * 1.9), (0.85, 0.85, 0.9), max(1, thick // 3), cv2.LINE_AA)
                cv2.circle(mask, (x, y), int(r * 2.2), 0.8, -1, cv2.LINE_AA)
            else:
                cv2.circle(layer, (x, y), r, (1.0, 1.0, 0.95), -1, cv2.LINE_AA)
                cv2.circle(layer, (x, y), int(r * 2.2), (0.35, 0.35, 0.3), max(1, thick // 4), cv2.LINE_AA)
                cv2.circle(mask, (x, y), int(r * 2.2), 0.9, -1, cv2.LINE_AA)
        q = (max(8, W // 4), max(8, H // 4))
        halo = cv2.resize(cv2.GaussianBlur(cv2.resize(mask, q, interpolation=cv2.INTER_AREA), (0, 0), 7 * H / 1080 + 2), (W, H))
        halo = np.clip(halo * 2.5, 0, 1)
        # 배경이 밝을수록 받침을 진하게 (도트가 하얗게 몰린 자리에서도 선이 묻히지 않게)
        bright = cv2.resize(cv2.resize(frame.mean(2), q, interpolation=cv2.INTER_AREA), (W, H))
        dark_lines = self.mode == 'evolve' and getattr(self, '_dark_lines', False)
        if composite:
            # 밝은 점 배경 — 선 둘레만 배경을 흐리게 가라앉힌 받침 위에 선을 얹는다 (점의 반짝임이 선을 갉아먹지 않게)
            calm = np.clip((bright - 0.28) / 0.3, 0, 1) * np.clip(halo * 1.4, 0, 1)
            soft = cv2.resize(cv2.GaussianBlur(cv2.resize(frame, q, interpolation=cv2.INTER_AREA), (0, 0), 3), (W, H)) * (1.0 if dark_lines else 0.6)
            frame = frame * (1 - calm[..., None]) + soft * calm[..., None]
        else:
            calm = np.zeros((H, W), np.float32)
        k_halo = (0.55 + 0.3 * np.clip((bright - 0.25) / 0.4, 0, 1)) * (1 - 0.55 * calm)  # 받침이 있는 자리는 덜 어둡게 (검은 얼룩처럼 보이지 않게)
        if dark_lines:
            k_halo = k_halo * 0.15
        frame = frame * (1 - k_halo[..., None] * halo[..., None])
        edge = cv2.GaussianBlur(under, (0, 0), 1.2 * H / 1080 + 0.4)
        if dark_lines:   # 밝은 배경 위 짙은 선 — 둘레를 살짝 밝혀 선이 배경 점들 사이에서 떠오르게
            frame = frame * (1 - 0.35 * np.clip(edge, 0, 1)[..., None]) + 0.35 * np.clip(edge, 0, 1)[..., None]
        else:
            frame = frame * (1 - (0.8 + 0.15 * np.clip((bright - 0.3) / 0.4, 0, 1))[..., None] * np.clip(edge, 0, 1)[..., None])
        lum = np.clip(np.maximum(layer.max(2), cov)[..., None], 0, 1)
        frame = frame * (1 - lum) + layer
        glow = cv2.resize(cv2.GaussianBlur(cv2.resize(layer, q, interpolation=cv2.INTER_AREA), (0, 0), 3 * H / 1080 + 1), (W, H))
        return frame + glow * 0.35


def label_overlay(sc_obj, W, H):
    font = find_font(max(12, int(H * 0.022)))
    small = find_font(max(10, int(H * 0.017)))
    if font is None:
        return None
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x, y = int(W * 0.035), int(H * 0.86)
    d.text((x, y), f'{sc_obj.act}  ·  장면 {sc_obj.sc.get("scene")}  ·  {sc_obj.emo_label}', font=font, fill=(220, 220, 230, 200))
    d.text((x, y + int(H * 0.035)), '   '.join(sc_obj.names), font=small, fill=(170, 175, 190, 170))
    a = np.asarray(img).astype(np.float32) / 255.0
    return a


def matte_path(out):
    out = Path(out)
    return out.with_name(out.stem + '_matte' + out.suffix)


def attach_bg_audio(out, bg):
    """배경 영상에 소리가 있으면 결과에 그대로 붙인다 (영상은 다시 인코딩하지 않음)"""
    tmp = out.with_name(out.stem + '_tmp_audio' + out.suffix)
    r = subprocess.run([ffmpeg_exe(), '-y', '-loglevel', 'error', '-i', str(out), '-i', str(bg), '-map', '0:v:0', '-map', '1:a:0?',
                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', str(tmp)])
    if r.returncode == 0 and tmp.exists():
        tmp.replace(out)
        print(f'  배경 소리 붙임 → {out.name}')
    else:
        print('  ! 배경 소리를 붙이지 못했습니다 (배경 영상에 소리가 없을 수 있음)')


def _story_hash(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:12]


def run_parallel(args, jobs):
    """장면마다 따로 렌더해(동시에 jobs 개) 이어 붙인다 — 결과는 한 줄로 돌린 것과 같다"""
    import time
    story = json.load(open(args.story, encoding='utf-8'))
    scenes = story['scenes'] if isinstance(story, dict) else story
    nums = sorted(s.get('scene', i + 1) for i, s in enumerate(scenes))
    out = Path(args.out).resolve()
    tmp = out.parent / f'{out.stem}_parts'
    tmp.mkdir(exist_ok=True)
    threads = max(1, (os.cpu_count() or 2) // jobs)
    base = [sys.executable, str(Path(__file__).resolve()), '--story', str(Path(args.story).resolve()),
            '--objects', str(Path(args.objects).resolve()), '--scene-sec', str(args.scene_sec), '--fps', str(args.fps),
            '--size', args.size, '--scale', str(args.scale), '--style', args.style, '--block', str(args.block),
            '--crf', str(args.crf), '--emerge', args.emerge, '--reversal', str(args.reversal), '--worker',
            '--contrast', str(args.contrast), '--seed-glow', str(args.seed_glow), '--dissolve-shift', str(args.dissolve_shift),
            '--threads', str(threads)]
    if args.bg: base += ['--bg', str(Path(args.bg).resolve())]
    if args.bg_json: base += ['--bg-json', str(Path(args.bg_json).resolve())]
    if args.no_label: base += ['--no-label']
    if args.no_reversal: base += ['--no-reversal']
    if args.multi_objects: base += ['--multi-objects']
    if args.no_doodles: base += ['--no-doodles']
    if args.no_targets: base += ['--no-targets']
    if args.alpha_out: base += ['--alpha-out']
    per = int(round(args.scene_sec * args.fps))
    total = per * len(nums)
    print(f'병렬 렌더 · 장면 {len(nums)}개를 동시에 {jobs}개씩 (프로세스당 스레드 {threads}) → {out.name}')
    waiting, running, parts = list(nums), {}, {}
    t0 = time.time()
    while waiting or running:
        while waiting and len(running) < jobs:
            k = waiting.pop(0)
            part, pf = tmp / f'part_{k:02d}.mp4', tmp / f'part_{k:02d}.progress'
            pf.write_text('0')
            log = open(tmp / f'part_{k:02d}.log', 'w', encoding='utf-8')
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            running[k] = (subprocess.Popen(base + ['--scenes', str(k), '--out', str(part), '--progress-file', str(pf)],
                                           stdout=log, stderr=subprocess.STDOUT, env=env), log)
            parts[k] = part
        time.sleep(2)
        for k in list(running):
            p, log = running[k]
            if p.poll() is not None:
                log.close()
                if p.returncode != 0:
                    sys.exit(f'장면 {k} 렌더 실패 — {tmp / f"part_{k:02d}.log"} 를 확인하세요')
                (tmp / f'part_{k:02d}.progress').write_text(str(per))
                del running[k]
        done = sum(int((tmp / f'part_{k:02d}.progress').read_text() or 0) for k in parts)
        el = time.time() - t0
        eta = el / done * (total - done) if done else 0
        print(f'\r  {done}/{total} 프레임 · {el:.0f}초 경과 · 남은 시간 약 {eta:.0f}초   ', end='', flush=True)
    print()
    lst = tmp / 'concat.txt'
    lst.write_text(''.join(f"file '{parts[k].as_posix()}'\n" for k in nums), encoding='utf-8')
    subprocess.run([ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(lst),
                    '-c', 'copy', '-movflags', '+faststart', str(out)], check=True)
    if args.alpha_out:
        lst_m = tmp / 'concat_matte.txt'
        lst_m.write_text(''.join(f"file '{matte_path(parts[k]).as_posix()}'\n" for k in nums), encoding='utf-8')
        subprocess.run([ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(lst_m),
                        '-c', 'copy', '-movflags', '+faststart', str(matte_path(out))], check=True)
    if args.bg_audio and args.bg:
        attach_bg_audio(out, Path(args.bg))
    metas = [json.load(open(parts[k].with_suffix('.json'), encoding='utf-8')) for k in nums]
    meta = dict(metas[0])
    meta['video'] = out.name
    if args.alpha_out:
        meta['matte'] = matte_path(out).name
    meta['scenes'], meta['law_map'], meta['reversal'] = [], [], []
    for i, m in enumerate(metas):
        off = i * per
        for mk in m['scenes']:
            mk2 = dict(mk, start_frame=mk['start_frame'] + off, start_sec=round((mk['start_frame'] + off) / args.fps, 2))
            if mk.get('figures'):
                mk2['figures'] = [dict(f, global_sec=round(mk2['start_sec'] + f['local_sec'], 1)) for f in mk['figures']]
            meta['scenes'].append(mk2)
        meta['law_map'] += m['law_map']
        for r in m.get('reversal', []):
            meta['reversal'].append(dict(r, global_sec=round(r['global_sec'] + off / args.fps, 2)))
    json.dump(meta, open(out.with_suffix('.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    shutil.rmtree(tmp, ignore_errors=True)
    for r in meta['reversal']:
        g = r['global_sec']
        print(f'  ★ 반전: 장면 {r["scene"]} 시작 후 {r["local_sec"]}초 = 전체 {int(g // 60)}:{g % 60:04.1f}')
    print(f'완료 → {out}  ·  {time.time() - t0:.0f}초  ·  장면 시각·법칙 대응표 → {out.with_suffix(".json")}')


def main():
    ap = argparse.ArgumentParser(description='꿈 오브제 창발 엔진 (시도 A · 파티클)')
    ap.add_argument('--story', default='dream_scenes.json', help='2팀 스토리보드 json')
    ap.add_argument('--objects', default='output_objects', help='장면별 투명 PNG 폴더 (scene_NN/obj_i_이름.png)')
    ap.add_argument('--out', default='object_emergence.mp4')
    ap.add_argument('--scene-sec', type=float, default=75.0, help='장면 길이(초) — 4장면 × 75초 = 5분')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--size', default='1920x1080')
    ap.add_argument('--scale', type=float, default=1.0, help='미리보기용 해상도 배율 (0.5 = 절반)')
    ap.add_argument('--scenes', default='', help='일부 장면만 (예: 1,3)')
    ap.add_argument('--bg', default='', help='배경 엔진 mp4 — 주면 통합 영상')
    ap.add_argument('--bg-json', default='', help='배경 엔진 video.json (장면 시작 시각)')
    ap.add_argument('--no-label', action='store_true', help='좌하단 서사 표지 끄기')
    ap.add_argument('--style', choices=['line', 'analog', 'digital'], default='line',
                    help='line: 손그림 선의 기하 도형 (기본 · 어린아이 로봇이 그리는 과정) · analog: 빛 입자 · digital: 사각 블록')
    ap.add_argument('--block', type=int, default=12, help='digital 블록 크기(1080p 기준 픽셀)')
    ap.add_argument('--crf', type=int, default=18)
    ap.add_argument('--emerge', choices=['point', 'cloud'], default='point', help='point: 한 점에서 서서히 드러남 · cloud: 예전 방식')
    ap.add_argument('--reversal', type=float, default=0.6, help='전(轉) 장면 반전 시점 (장면 안 비율 · 0.6 = 75초 중 45초)')
    ap.add_argument('--no-reversal', action='store_true', help='반전 끄기')
    ap.add_argument('--seed-glow', type=float, default=1.0, help='오브제가 드러나기 전 시작점 빛의 세기 (0 = 끔)')
    ap.add_argument('--dissolve-shift', type=float, default=0.0, help='오브제가 풀리는 시점 앞뒤 조정 (장면 비율 · +0.02 = 1.5초 늦게)')
    ap.add_argument('--contrast', type=float, default=-1, help='밝은·색 배경 대비 보정 세기 0~1 (기본: 통합이면 1, 오브제만이면 0)')
    ap.add_argument('--no-targets', action='store_true',
                    help='진화 목표 선화(targets.json)가 있어도 쓰지 않는다 (손그림 형상 · PNG 윤곽으로)')
    ap.add_argument('--no-doodles', action='store_true',
                    help='손그림 형상(doodles.json) 대신 오브제 PNG 윤곽으로 그린다')
    ap.add_argument('--doodle-llm', action='store_true',
                    help='손그림 형상을 고를 때 Claude 가 이야기 맥락까지 보고 고른다 (ANTHROPIC_API_KEY 필요)')
    ap.add_argument('--multi-objects', action='store_true',
                    help='선화에서 예전처럼 오브제 여러 개를 나란히 그린다 (기본은 하나의 오브제가 태어나 변해 간다)')
    ap.add_argument('--alpha-out', action='store_true',
                    help='오브제만 + 투명도: 검은 바탕 오브제 영상과 투명도(흑백) 영상 _matte.mp4 를 함께 낸다 (다른 팀이 자기 배경에 합성할 때)')
    ap.add_argument('--bg-audio', action='store_true', help='--bg 로 넣은 배경 영상의 소리를 결과에 그대로 붙인다')
    ap.add_argument('--jobs', default='auto', help='동시에 렌더할 장면 수 (auto = CPU 에 맞춰 최대 4 · 1 = 한 줄로)')
    ap.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--progress-file', default='', help=argparse.SUPPRESS)
    ap.add_argument('--threads', type=int, default=0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.threads:
        cv2.setNumThreads(args.threads)
    reversal = None if args.no_reversal else args.reversal

    W, H = [int(int(v) * args.scale) // 2 * 2 for v in args.size.lower().split('x')]
    digital = args.style == 'digital'
    cell = max(4, round(args.block * H / 1080))
    if digital and args.out == 'object_emergence.mp4':
        args.out = 'object_emergence_digital.mp4'
    doodle_path = Path(args.objects) / 'doodles.json'
    if args.style == 'line' and not args.multi_objects and not args.no_doodles and not args.worker:
        # 손그림 형상 준비 (처음 한 번 · 대본이 바뀌면 다시) — 병렬 작업이 나뉘기 전에
        stale = True
        if doodle_path.exists():
            try:
                stale = json.loads(doodle_path.read_text(encoding='utf-8')).get('story_hash') != _story_hash(args.story)
            except Exception:
                stale = True
        if stale:
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import doodles as _dd
                res = _dd.build(args.story, args.objects, use_llm=args.doodle_llm)
                if any(o.get('strokes') for sc_ in res['scenes'] for o in sc_['objects']):
                    res['story_hash'] = _story_hash(args.story)  # 낙서를 하나도 못 받았으면 다음 실행 때 다시 시도
                    doodle_path.write_text(json.dumps(res, ensure_ascii=False), encoding='utf-8')
                else:
                    print('  ! 손그림 형상을 하나도 받지 못해(인터넷?) 이번엔 PNG 윤곽으로 그립니다')
            except Exception as e:
                print(f'  ! 손그림 형상을 준비하지 못해 PNG 윤곽으로 그립니다 ({e})')
    if not args.worker and not args.scenes:
        jobs = (min(4, max(1, (os.cpu_count() or 2) // 2)) if args.jobs == 'auto' else int(args.jobs))
        if jobs > 1:
            return run_parallel(args, jobs)
    story = json.load(open(args.story, encoding='utf-8'))
    scenes = story['scenes'] if isinstance(story, dict) else story
    scenes = sorted(scenes, key=lambda s: s.get('scene', 0))
    order = list(range(len(scenes)))
    if args.scenes:
        want = {int(s) for s in args.scenes.split(',')}
        order = [i for i in order if scenes[i].get('scene') in want]
    n_all = len(scenes)
    targets_by_scene = {}   # 진화 목표 선화 (targets.py) — 있으면 손그림 형상보다 먼저 쓴다
    tpath = Path(args.objects) / 'targets.json'
    if args.style == 'line' and not args.multi_objects and not args.no_targets and tpath.exists():
        try:
            tj = json.loads(tpath.read_text(encoding='utf-8'))
            if tj.get('story_hash') == _story_hash(args.story):
                for e in tj['scenes']:
                    targets_by_scene[e['scene']] = e['objects']
            elif not args.worker:
                print('  ! targets.json 이 지금 대본과 다른 판이라 쓰지 않습니다 (targets.py 를 다시 돌리세요)')
        except Exception as e:
            print(f'  ! targets.json 을 읽지 못했습니다 ({e})')
    doodles_by_scene = {}
    if args.style == 'line' and not args.multi_objects and not args.no_doodles and doodle_path.exists():
        try:
            for e in json.loads(doodle_path.read_text(encoding='utf-8'))['scenes']:
                doodles_by_scene[e['scene']] = e['objects']
        except Exception as e:
            print(f'  ! doodles.json 을 읽지 못했습니다 ({e})')
    composite = bool(args.bg)
    if args.alpha_out and composite:
        sys.exit('--alpha-out 은 오브제만 렌더할 때 쓴다 (--bg 와 같이 쓰지 않는다)')
    if args.alpha_out:
        args.no_label = True
    contrast = (1.0 if composite else 0.0) if args.contrast < 0 else args.contrast
    seed = int(hashlib.sha1(json.dumps(scenes, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    print(f'꿈 오브제 창발 엔진 · {args.style} · {W}x{H} · {args.fps}fps · 장면당 {args.scene_sec:g}초 · {"통합" if composite else "오브제만"} · 시드 {seed}')

    bg = Background(W, H, args.bg or None, args.bg_json or None, n_all, args.scene_sec)
    if digital:
        if not composite:  # 디지털 바탕 — 평평한 어둠 위에 아주 옅은 격자
            bg.dark = np.full((H, W, 3), [0.035, 0.037, 0.050], np.float32)
            bg.dark[::cell * 4, :] += 0.018
            bg.dark[:, ::cell * 4] += 0.018
        gap_mask = np.ones((H, W, 1), np.float32)  # 블록 사이 가는 틈 — 타일처럼 보이게
        gap_mask[::cell] = 0.72
        gap_mask[:, ::cell] = 0.72
    out = Path(args.out)
    cmd = [ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
           '-r', str(args.fps), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(args.crf),
           '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    enc_m = None
    if args.alpha_out:
        matte = matte_path(out)
        enc_m = subprocess.Popen(cmd[:-1] + [str(matte)], stdin=subprocess.PIPE)

    law_map, marks = [], []
    prev_cloud = None
    frames_per_scene = int(round(args.scene_sec * args.fps))
    total = frames_per_scene * len(order)
    last = max(order) if order else -1
    fog_col = np.array([0.10, 0.11, 0.14], np.float32)
    done = 0
    import time
    t0 = time.time()
    reversals = []
    for si in range(last + 1):
        sc = scenes[si]
        files = load_objects_index(args.objects, sc.get('scene', si + 1), sc.get('objects') or [])
        if si not in order and args.style == 'line':
            # 선화는 앞 장면 상태를 이어받지 않는다 — 난수 순서만 맞추려고 만들고 넘긴다
            Scene(sc, si, n_all, files, W, H, prev_cloud, rng, args.style, cell, args.emerge, reversal, quiet=True,
                  seed_glow=args.seed_glow, dissolve_shift=args.dissolve_shift)
            continue
        if si not in order:
            # 앞 장면 빨리 감기 — 그리지 않고 입자 계산만 한다. 다음 장면이 앞 장면 잔해에서 태어나므로,
            # 장면을 나눠 렌더해도 한 번에 돌린 것과 같은 결과가 나오게 한다.
            S = Scene(sc, si, n_all, files, W, H, prev_cloud, rng, args.style, cell, args.emerge, reversal, quiet=True,
                      seed_glow=args.seed_glow, dissolve_shift=args.dissolve_shift)
            for f in range(frames_per_scene):
                S.step(f / frames_per_scene, f / args.fps)
            prev_cloud = S.cloud()
            print(f'  장면 {sc.get("scene")} 빨리 감기 완료')
            continue
        S = Scene(sc, si, n_all, files, W, H, prev_cloud, rng, args.style, cell, args.emerge, reversal,
                  seed_glow=args.seed_glow, dissolve_shift=args.dissolve_shift)
        if S.rev is not None:
            loc = S.rev * args.scene_sec
            g = done / args.fps + loc
            reversals.append({'scene': sc.get('scene'), 'local_sec': round(loc, 2), 'global_sec': round(g, 2)})
            print(f'    ★ 반전: 장면 {sc.get("scene")} 시작 후 {loc:.1f}초 (이 영상의 {int(g // 60)}:{g % 60:04.1f})')
        law_map.append({'scene': sc.get('scene'), 'act': S.act, 'emotion': S.emo_label,
                        'objects': S.names, 'laws': S.law_log})
        for e in S.law_log:
            if e['applied']:
                print('    ✓', e['law'], '→', '; '.join(f'{k}: {", ".join(v)}' for k, v in e['behaviors'].items()))
            else:
                print('    ·', e['law'], '→', e['reason'])
        marks.append({'scene': sc.get('scene'), 'act': S.act, 'start_frame': done, 'start_sec': round(done / args.fps, 2)})
        label = None if (args.no_label or composite) else label_overlay(S, W, H)
        LS = None
        if args.style == 'line':
            keep = [i for i, fp in enumerate(files) if fp is not None]
            if args.multi_objects:  # 예전 방식 — 오브제 여러 개를 나란히
                LS = LineScene(S, files, keep, seed + si * 7919, args.scene_sec)
            else:                   # 하나의 오브제 — 숨어 있던 형상이 이야기 순서대로 드러나고, 꿈처럼 흐트러지며 변해 간다
                dd = doodles_by_scene.get(sc.get('scene', si + 1))
                prev_dd = None
                if si > 0:
                    for e in reversed(doodles_by_scene.get(scenes[si - 1].get('scene', si)) or []):
                        if e.get('strokes'):
                            prev_dd = e
                            break
                prev_files = []
                if si > 0:
                    psc = scenes[si - 1]
                    prev_files = [p for p in load_objects_index(args.objects, psc.get('scene', si), psc.get('objects') or []) if p is not None]
                tg = targets_by_scene.get(sc.get('scene', si + 1))
                prev_tg = None
                if si > 0:
                    for e in reversed(targets_by_scene.get(scenes[si - 1].get('scene', si)) or []):
                        if e.get('strokes'):
                            prev_tg = e
                            break
                LS = OneObjectScene(S, files, keep, seed + si * 7919, args.scene_sec, prev_files, si == len(scenes) - 1,
                                    doodle_scene=dd, prev_doodle=prev_dd, target_scene=tg, prev_target=prev_tg)
                if LS.mode == 'evolve':
                    marks[-1]['ga'] = LS.ga_log   # 렌더가 끝난 뒤 채워진다 (같은 리스트)
                if LS.mode in ('doodle', 'evolve'):   # 무엇을 언제 그렸는지 (설명용)
                    marks[-1]['figures'] = [{'object': st['name'], 'figure': st['category'], 'local_sec': round(r, 1),
                                             'global_sec': round(done / args.fps + r, 1)}
                                            for st, r in zip(LS.stages, LS.reveal_t)]
                    for f in marks[-1]['figures']:
                        print(f"    ◇ {f['local_sec']:5.1f}초 {f['object']} → {f['figure']}")
        for f in range(frames_per_scene):
            tau = f / args.fps
            u = f / frames_per_scene
            if LS is not None:
                draw = lambda b, u=u, tau=tau: LS.render(b, u, tau, composite)
            else:
                step_out = S.step(u, tau)
                if digital:
                    draw = lambda b: compose_digital(S, b, step_out, contrast, cell, gap_mask)
                else:
                    draw = lambda b, u=u: compose_analog(S, b, step_out, u, composite, contrast, fog_col)
            if args.alpha_out:
                # 오브제만 + 투명도 — 검은 바탕 · 흰 바탕에 각각 그려 차이로 투명도를 구한다 (합성 식이 바탕에 대해 1차라 정확하다)
                f0 = draw(np.zeros((H, W, 3), np.float32))
                f1 = draw(np.ones((H, W, 3), np.float32))
                alpha = np.clip(1 - (f1 - f0).mean(2), 0, 1)
                enc.stdin.write((np.clip(f0, 0, 1) * 255).astype(np.uint8).tobytes())
                enc_m.stdin.write(np.repeat((alpha * 255).astype(np.uint8)[..., None], 3, 2).tobytes())
            else:
                frame = draw(bg.get(si, tau))
                # 장면 경계 — 들어오고 나갈 때 1초씩 부드럽게
                edge = min(1.0, tau / 1.0, (args.scene_sec - tau) / 1.0) if not composite else 1.0
                if label is not None:
                    la = label[..., 3:4] * edge
                    frame = frame * (1 - la) + label[..., :3] * la
                enc.stdin.write((np.clip(frame, 0, 1) * 255).astype(np.uint8).tobytes())
            done += 1
            if args.progress_file and done % 30 == 0:
                Path(args.progress_file).write_text(str(done))
            if done % (args.fps * 5) == 0 or done == total:
                el = time.time() - t0
                print(f'\r  {done}/{total} 프레임 · {el:.0f}초 경과 · 남은 시간 약 {el / done * (total - done):.0f}초   ', end='', flush=True)
        prev_cloud = S.cloud()
        print()
    enc.stdin.close()
    enc.wait()
    if enc_m is not None:
        enc_m.stdin.close()
        enc_m.wait()
    if args.bg_audio and composite and not args.worker:
        attach_bg_audio(out, Path(args.bg))
    meta = {'video': out.name, 'fps': args.fps, 'size': [W, H], 'scene_sec': args.scene_sec, 'seed': seed,
            'mode': 'integrated' if composite else ('objects_alpha' if args.alpha_out else 'objects_only'),
            'style': args.style, 'emerge': args.emerge, 'reversal': reversals, 'scenes': marks, 'law_map': law_map}
    if args.alpha_out:
        meta['matte'] = matte_path(out).name
        meta['composite'] = 'out = bg * (1 - matte) + fill   (fill = 이 영상 · 이미 matte 를 곱한 색 · matte = 흰색일수록 오브제)'
    json.dump(meta, open(out.with_suffix('.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'완료 → {out}  ·  장면 시각·법칙 대응표 → {out.with_suffix(".json")}')


if __name__ == '__main__':
    main()
