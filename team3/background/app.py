from flask import Flask, jsonify, send_from_directory, Response, request
import re
import struct
import base64
from flask_cors import CORS
import json
import mimetypes
import os
import sys
import subprocess
import threading

# ─────────────────────────────────────────────────────────────
# 아피찻퐁 꿈 이미지 실시간 생성기 — 백엔드 (시스템 I)
#
# 이 파일은 '변환기'가 아니라 '전달자'다.
# 예전에는 여기서 OpenCV로 Canny 윤곽선을 따서 좌표를 넘겼지만,
# 그 방식은 형태를 그대로 베끼는 것이라 추상과 거리가 멀었다.
# 이제 추상화는 전부 브라우저에서 픽셀을 빨아들이며 일어난다.
# (OpenCV·numpy 불필요)
#
# ★ 2026-09-25 — 서사의 출처가 바뀌었다
#   예전엔 스토리 순서·기승전결이 이 파일 안의 STORY 리스트에 하드코딩돼 있었고,
#   폴더를 glob 으로 훑어 파일명 끝 숫자로 이미지·사운드를 짝지었다.
#   1·2팀이 story_data.json 을 넘기기로 하면서 그 두 가지가 모두 필요 없어졌다.
#     · 서사 정의  → story_data.json (1·2팀 산출물). 이 파일은 그걸 읽어 넘길 뿐이다.
#     · 파일 짝짓기 → JSON 이 scene_file / sound_file 로 직접 지정한다. 추측하지 않는다.
#   사운드도 .avi → .mp3 로 확정돼, 요청마다 AVI를 뜯어 AAC를 뽑던 avi_to_aac 를
#   걷어냈다. 백엔드는 이제 정적 파일을 그대로 흘려보낸다(Range 요청 지원).
#   (더미 .aac 는 원본 .avi 에서 한 번 뽑아 둔 것. 원본 .avi 는 백업 Capstone2_Team3_0917/260917_dummy/ 에 있다)
#
# ★ 2026-09-27 — 입력이 두 갈래로 나뉘었다
#   2팀이 실제로 보낸 스토리보드(dream_scenes.json)는 우리가 짐작한 규격과 달랐다.
#   이미지·사운드 파일명이 없고, 장면마다 '글'만 있다 — story / backgrounds / objects /
#   emotions(자유 문장) / physics_laws / vector. 미팅 정리(0917)상 스토리보드 → 이미지는
#   우리(3팀) 몫이므로 이게 맞는 인계다. 규격은 넘기는 쪽에 맞춘다.
#     · input/storyboard/  2팀 실입력. 기본값. 배경 이미지는 scene_01.png … 로 여기 놓인다
#                    (tools/make_prompts.py → 이미지 생성기로 만든 사진)
#     · input/dummy/ 09-13 기준 자료. `python app.py --dummy` 로만 쓴다.
#                    (10-03 폴더와 측정 도구 measure_dream.py 는 지웠다 — 코드만 남아 폴더가 없으면 장면 0)
#   두 폴더를 섞지 않는 이유: 더미가 실입력 자리에 조용히 끼어들면 '2팀 데이터로 돌고 있다'고
#   착각하게 되고, 반대로 실입력이 기준 자리에 들어가면 회귀 비교가 무의미해진다.
# ─────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, 'input')           # 09-27 정리: 입력은 모두 input/ 아래
DUMMY_DIR = os.path.join(INPUT_DIR, 'dummy')
STORYBOARD_DIR = os.path.join(INPUT_DIR, 'storyboard')
DB_DIR = os.path.join(BASE_DIR, 'db')                 # 참조 DB(json)와 그 원본·빌드 도구

# --dummy 면 input/storyboard/ 가 있어도 기준 자료로 돈다 (회귀 측정·09-13 화면 확인용)
FORCE_DUMMY = '--dummy' in sys.argv

# 더미 모드에서 story_data.json 을 찾는 순서.
STORY_PATHS = [
    os.path.join(DUMMY_DIR, 'story_data.json'),
    os.path.join(BASE_DIR, 'story_data.json'),
]

IMAGE_EXT = ('.png', '.jpg', '.jpeg')

# 결과물 내보내기 — 장면마다 대표 프레임 PNG + 메타데이터 (09-27).
# 0917 미팅 4팀 항목 "이미지 생성팀 결과물을 Unity·영상 시스템에서 바로 받을 수 있게 형식을 미리 정한다"의 초안.
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

# 브라우저가 바로 재생하는 오디오 확장자. 실데이터는 .mp3 로 온다.
# (.aac 는 더미 원본 .avi 에서 뽑아둔 것. .avi 는 목록에 없다 — 크롬이 못 읽는다)
AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.flac'}
mimetypes.add_type('audio/aac', '.aac')
mimetypes.add_type('audio/mp4', '.m4a')

ACT_KEYS = ['기', '승', '전', '결']


def read_scene_list(path):
    """JSON 한 파일 → 장면 리스트. 배열이든 {"scenes": [...]} 든 받는다. 못 읽으면 None."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        # 조용히 넘어가면 '왜 화면이 비지?'의 원인을 영영 못 찾는다. 반드시 남긴다.
        print("서사 파일을 읽지 못했습니다 (%s): %s" % (path, e))
        return None
    if isinstance(data, dict):
        data = data.get('scenes') or data.get('장면') or []
    return normalize_rows(data) if isinstance(data, list) and data else None


def scene_number(row, i):
    """장면 번호 — 정수 · "3" · "scene_3"/"장면 3" 을 모두 받는다. 없으면 배열 순서(i+1).

       10-05 1팀: 2팀 스토리보드는 형식은 같지만 내용은 매번 다르게 나온다(오픈엔디드).
       번호 표기가 조금 달라져도 서버가 500 으로 죽지 않게 한다. 0 도 번호로 받는다(예전 `or` 는 0 을 버렸다)."""
    v = row.get('act') if row.get('act') is not None else row.get('scene')
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    if isinstance(v, str) and re.search(r'\d+', v):
        return int(re.search(r'\d+', v).group())
    return i + 1


def normalize_rows(rows):
    """장면 목록 → 번호(_num)를 붙여 번호순으로 정렬한 목록. 장면이 아닌 항목(null 등)은 버린다.

       번호가 겹치면 배열 순서로 다시 매긴다 — 그대로 두면 여러 장면이 scene_01.png 하나를 나눠 쓴다."""
    good = [r for r in rows if isinstance(r, dict)]
    if len(good) < len(rows):
        print("장면이 아닌 항목 %d개를 건너뜁니다." % (len(rows) - len(good)))
    nums = [scene_number(r, i) for i, r in enumerate(good)]
    if len(set(nums)) < len(nums):
        print("장면 번호가 겹칩니다 %s — 배열 순서로 1부터 다시 매깁니다." % nums)
        nums = list(range(1, len(good) + 1))
    return [dict(r, _num=n) for n, r in sorted(zip(nums, good), key=lambda t: t[0])]


def pick_source():
    """이번 요청에 쓸 입력을 고른다 → (모드, JSON 경로 또는 None, 미디어 폴더).

       input/storyboard/ 에 JSON 이 있으면 그게 실입력이다(가장 최근 파일).
       2팀이 새 판을 보낼 때 파일명이 바뀔 수 있어, 이름을 못박지 않고 최신 것을 쓴다.
       요청마다 다시 고르므로 파일을 바꿔 넣고 새로고침만 하면 된다(서버 재시작 불필요)."""
    if not FORCE_DUMMY and os.path.isdir(STORYBOARD_DIR):
        found = [os.path.join(STORYBOARD_DIR, n) for n in os.listdir(STORYBOARD_DIR)
                 if n.lower().endswith('.json')]
        if found:
            return 'storyboard', max(found, key=os.path.getmtime), STORYBOARD_DIR
    for path in STORY_PATHS:
        if os.path.exists(path):
            return 'dummy', path, DUMMY_DIR
    return 'dummy', None, DUMMY_DIR


def scan_fallback():
    """더미 모드에서 story_data.json 이 없을 때만 쓰는 최소 대비책.

       예전처럼 파일명으로 서사를 추측하지는 않는다. 폴더에 있는 이미지를 순서대로
       늘어놓고 기승전결만 균등 배분해, 데이터가 늦어도 화면은 돌게 한다.
       감정 라벨은 비워둔다 — 없는 값을 지어내면 화면이 거짓말을 한다."""
    if not os.path.isdir(DUMMY_DIR):
        return []
    names = sorted(os.listdir(DUMMY_DIR))
    images = [n for n in names if os.path.splitext(n)[1].lower() in IMAGE_EXT]
    sounds = [n for n in names if os.path.splitext(n)[1].lower() in AUDIO_EXT]
    out = []
    for k, img in enumerate(images):
        pos = min(3, int(k * 4 / max(1, len(images))))
        out.append({
            "act": k + 1,
            "scene_file": img,
            "sound_file": sounds[k % len(sounds)] if sounds else None,
            "stage": ACT_KEYS[pos],
            "title": os.path.splitext(img)[0],
            "emotion": None,
        })
    print("story_data.json 이 없어 폴더 %d장으로 임시 진행합니다 (감정 라벨 없음)." % len(out))
    return out


# 1팀 감정 7종 (09-27 2팀 확인) — 기본 6 + 중립. 2팀 main_emotion.label 은 이 중 하나로 온다.
EMO_SEVEN = ('기쁨', '슬픔', '분노', '공포', '놀람', '혐오', '중립')

# 2팀 emotions(자유 문장) → 1팀 7종. main_emotion 이 없을 때만 쓰는 대비책이다.
# 2팀은 "점증하는 불안과 공포" 같은 문장을 준다. 프론트 가중치 표는 라벨 한 단어로만 걸리므로
# 문장 안의 낱말로 짝짓는다. 뜻이 갈리는 말(집착·집요함·위화감·정적)은 일부러 넣지 않았다 —
# 억지로 붙이면 없는 감정을 지어내는 것이다.
# 7종에 없는 결(불안·공허·그리움·평온)은 가장 가까운 기본 감정으로 모은다 — 세밀함은 줄지만
# 1팀 → 2팀 → 3팀이 같은 말을 쓰게 된다. 평온은 기본 감정이 없어 중립(가중치 없음)으로 둔다.
EMO_KEYWORDS = [
    ('불안', '공포'), ('초조', '공포'), ('긴장', '공포'),
    ('공포', '공포'), ('두려', '공포'), ('무서', '공포'), ('겁', '공포'),
    ('우울', '슬픔'), ('슬픔', '슬픔'), ('슬프', '슬픔'), ('좌절', '슬픔'), ('무력', '슬픔'), ('체념', '슬픔'), ('절망', '슬픔'),
    ('공허', '슬픔'), ('허무', '슬픔'), ('상실', '슬픔'), ('고독', '슬픔'), ('외로', '슬픔'),
    ('그리움', '슬픔'), ('그리운', '슬픔'), ('향수', '슬픔'), ('갈망', '슬픔'),
    ('평온', '중립'), ('평화', '중립'), ('안도', '중립'), ('고요', '중립'),
    ('경이', '놀람'), ('경외', '놀람'), ('신비', '놀람'), ('놀라', '놀람'), ('놀람', '놀람'), ('경악', '놀람'),
    ('혐오', '혐오'), ('역겨', '혐오'), ('구역질', '혐오'), ('불쾌', '혐오'),
    ('기쁨', '기쁨'), ('환희', '기쁨'), ('행복', '기쁨'),
    ('분노', '분노'), ('격노', '분노'), ('화가', '분노'),
]


def main_emotion(row):
    """2팀 main_emotion(대표 감정) → (라벨, 세기 또는 None). 없으면 (None, None).

       합의 모양은 {"label": "슬픔", "intensity": 0.8} 이다. 2팀 코드가 조금 다르게 내보내도
       받도록 흔한 변형(문자열만 · emotion/value/score 키 · 다른 필드 이름)을 함께 받는다."""
    v = row.get('main_emotion') or row.get('primary_emotion') or row.get('emotion_main')
    if isinstance(v, str):
        return (v.strip() or None), None
    if isinstance(v, dict):
        lab = v.get('label') or v.get('emotion') or v.get('name')
        inten = v.get('intensity', v.get('value', v.get('score')))
        try:
            inten = None if inten is None else float(inten)
        except (TypeError, ValueError):
            inten = None
        return (lab.strip() if isinstance(lab, str) and lab.strip() else None), inten
    return None, None


def label_from_phrases(phrases):
    """감정 문장 목록 → (라벨, 근거 문장). 못 찾으면 (None, None).

       2팀이 앞에 적은 감정을 주 감정으로 본다: 앞 문장부터 보며 처음 짝지어지는 것을 쓴다.
       한 문장 안에서는 먼저 나온 낱말을 쓴다("불안과 공포" → 불안)."""
    if isinstance(phrases, str):
        phrases = [phrases]
    for ph in phrases or []:
        if not isinstance(ph, str):
            continue
        hits = [(ph.find(k), lab) for k, lab in EMO_KEYWORDS if k in ph]
        if hits:
            return min(hits)[1], ph
    return None, None


# ── 참조 작가 가중치 (PDF 시스템 I 참조 작가 4명, 09-27) ─────────────────────
# 아피찻퐁은 늘 바탕(최소 50%)이고, 나머지 3명은 **장면 글이 부를 때만** 섞인다(무작위 금지).
# 글은 backgrounds(우리가 그리는 것) 를 주로, story 본문을 보조로 읽는다.
# 낱말은 각 작가 DB 의 수치 성격에 맞췄다 (artist_db.json · Work Log 28):
#   마에다   채도 높은 풍경 · 밝은 띠가 화면 위쪽(하늘·지평선)  → 안개·언덕·들판·설원·노을·하늘
#   디갈라카스 흑백 · 가운데 한 대상 · 여백                       → 물가·호수·얼음·바위·선착장·정적
#   폰타나   한 색으로 몰린 색면 · 낮은 대비                       → 선명한 색 이름·햇빛·모래·해변
# ※ 흔한 글자는 일부러 뺐다: '물'(물체·건물), '눈'(눈빛), '나무'(자작나무가 모든 장면에 있다), '색'(회색).
ARTIST_KEYWORDS = {
    'maeda':     ['안개', '언덕', '구릉', '들판', '밭', '초원', '설원', '눈 덮인', '눈밭', '노을', '황혼', '석양',
                  '새벽', '지평선', '하늘', '구름'],
    'digalakis': ['호수', '물가', '수면', '물결', '바다', '얼음', '얼어붙은', '바위', '선착장', '부두', '잔교',
                  '고요', '정적', '적막', '여백', '텅 빈', '홀로', '한 그루'],
    'fontana':   ['붉은', '노란', '초록', '파란', '푸른', '주황', '선명한', '햇빛', '햇살', '모래', '해변', '사막'],
}
# 본문(story)을 읽지 않는 작가 — 폰타나의 색 낱말은 본문에서는 대개 **오브제의 색**이다
# (09-27 실측: '초록빛 가죽 표지'·'붉은 실선'이 폰타나를 불렀다). 색은 배경 묘사에 있을 때만 배경의 색이다.
ARTIST_BG_ONLY = {'fontana'}
# 폰타나의 색 낱말은 '선명한 색'일 때만 — 09-28 2팀 장면 2 "색 바랜 초록 벽"이 폰타나를 33% 불렀다.
# 바랜 색은 폰타나(선명한 색면)와 반대 방향이라, 이런 말이 붙은 배경 항목에서는 폰타나를 세지 않는다.
FADED = ('바랜', '탁한', '흐린', '빛 잃은')
ARTIST_MAX = 0.5      # 세 작가 합의 상한 — 아피찻퐁 막별 목표(09-13 확정)가 늘 절반 이상을 지킨다
ARTIST_FULL = 3.0     # 이 점수에서 상한에 닿는다 (배경 낱말 3개쯤)


def artist_weights(row):
    """장면 글 → ({작가: 가중치}, {작가: [근거 낱말]}). 글이 없으면(더미) 빈 값 = 예전 동작 그대로."""
    bg = ' '.join(b for b in (row.get('backgrounds') or []) if isinstance(b, str))
    story = row.get('story') if isinstance(row.get('story'), str) else ''
    score, basis = {}, {}
    bg_vivid = ' '.join(b for b in (row.get('backgrounds') or [])
                        if isinstance(b, str) and not any(f in b for f in FADED))
    for a, words in ARTIST_KEYWORDS.items():
        hit_bg = [w for w in words if w in (bg_vivid if a == 'fontana' else bg)]
        n_story = 0 if a in ARTIST_BG_ONLY else sum(story.count(w) for w in words)
        sc = len(hit_bg) + min(1.0, n_story * 0.2)       # 본문은 보조 — 작가당 1점까지만
        if sc > 0:
            score[a] = sc
            basis[a] = hit_bg or sorted({w for w in words if w in story and a not in ARTIST_BG_ONLY})[:3]
    tot = sum(score.values())
    if tot <= 0:
        return {}, {}
    W = ARTIST_MAX * min(1.0, tot / ARTIST_FULL)
    return {a: round(W * v / tot, 3) for a, v in score.items()}, basis


# ── 꿈의 물리 법칙 (2팀 physics_laws → 엔진 물리, 09-27) ──────────────────────
# 2팀은 장면마다 '이 꿈에서만 성립하는 물리'를 문장으로 준다. 우리 엔진은 바람·빛·흔들림·안개를
# 가진 물리 엔진이라, 그중 **배경에서 일어나는 현상**을 엔진 동작으로 옮긴다(미팅 3-4 물리엔진 · 3-7 연관성).
# 문장 하나가 [A 낱말 중 하나] 와 [B 낱말 중 하나] 를 **모두** 가질 때만 그 법칙으로 본다 —
# '빛'만 있다고 빛 법칙이 아니라 '빛이 … 밝아짐' 이어야 한다.
# ※ 새·사슴·노인·표지처럼 오브제가 주어인 법칙(스스로 회전·콧김·손가락…)은 시스템 II 몫이라
#   여기 없는 말로 남는다. 소리에 관한 법칙도 사운드 담당이 정해질 때까지 두지 않는다.
#   못 옮긴 문장 수는 패널에 그대로 보인다 — 다 반영한 척하지 않는다.
LAW_RULES = [
    # 효과 키    패널 이름         A (무엇이)                        B (어떻게)
    ('still',    '바람 없는 흔들림', ['불지 않', '바람 없', '바람이 없'],  ['흔들']),
    ('glowrise', '원인 없는 빛',    ['빛'],                           ['밝아']),
    ('breathe',  '형체의 숨',       ['굵기', '높이', '크기'],          ['변함', '변하', '변해']),
    ('thin',     '가늘어져 사라짐',  ['가늘어', '옅어', '희미해'],      ['사라']),
    ('fixed',    '고정된 거리',      ['거리'],                         ['고정']),
    ('desync',   '어긋난 박자',      ['박자', '리듬', '주기'],          ['어긋']),
]


def says(p, w):
    """문장 p 가 w 를 '긍정으로' 말하는가. 09-28 2팀 장면 2 "높이가 변하지 않음"이
       '형체의 숨'(높이가 변함)으로 잡혀 뜻이 뒤집혔다 — 바로 뒤가 '지 않'·'지 못'이면 아니다."""
    return any(not p.startswith(('지 않', '지 못'), i + len(w))
               for i in [m.start() for m in re.finditer(re.escape(w), p)])


def laws_from(row):
    """physics_laws 문장 목록 → ([{key, name, src}], 전체 문장 수). 한 효과는 한 번만(첫 근거 문장)."""
    laws = [p for p in (row.get('physics_laws') or []) if isinstance(p, str)]
    out, seen = [], set()
    for p in laws:
        for key, name, a, b in LAW_RULES:
            if key not in seen and any(w in p for w in a) and any(says(p, w) for w in b):
                out.append({"key": key, "name": name, "src": p})
                seen.add(key)
    return out, len(laws)


# ── 공기 중의 물기 (PDF 아날로그 키워드 '비', 09-27) ────────────────────────────
# PDF 시스템 I 키워드(빛·몽환적·단순·바람·비·안개·여백) 중 '비'를 **글이 부를 때만** 화면에 들인다.
# 이번 2팀 4장면에는 내리는 비·눈이 없고 김(오르는 물기)·서리(내려앉는 물기)만 있어,
# 사용자 결정(09-27)으로 '비'를 '공기 중의 물기' 네 가지로 넓혀 읽는다. 발표에서도 그렇게 설명한다.
#   rain 비 · snow 눈(내리는 것만 — '눈 덮인 땅'은 쌓인 눈이라 아니다) · frost 서리 · steam 김
# ★ 오브제 거르기 — 2팀이 objects 에 적은 것은 시스템 II 몫이다.
#   ① 물기 자체가 objects 에 있으면(장면 1 '김', 장면 2 '서리') 그 장면에선 쓰지 않는다
#   ② 오브제 명사가 들어간 문장('표지의 갈라진 틈에서 김이…')도 쓰지 않는다
#   backgrounds 항목은 2팀이 배경이라고 적은 것이라 그대로 믿는다.
MOIST_RULES = [
    # 종류     패널 이름    [물기 낱말]                                   [함께 있어야 하는 낱말] (없으면 낱말만으로)
    ('rain',  '비',   ['비가 내', '비가 온', '비가 쏟', '빗방울', '빗줄기', '빗물', '소나기', '이슬비', '가랑비', '장대비'], None),
    ('snow',  '눈',   ['눈이 내', '눈이 온', '눈발', '눈송이', '눈이 흩날', '눈보라', '진눈깨비', '함박눈', '싸락눈'], None),
    ('frost', '서리', ['서리', '성에'],                                ['내려앉', '앉는', '앉았', '맺히', '맺혀', '낀다', '끼어']),
    ('steam', '김',   ['김이', '김 서린', '김은', '수증기', '입김'],        None),
]
MOIST_NOUN = {'rain': '비', 'snow': '눈', 'frost': '서리', 'steam': '김'}
JOSA = r'(?:이|가|을|를|은|는|의|에|도|만|와|과|로|으로|에서|처럼)?(?=[\s,.·)!?]|$)'


def object_heads(row):
    """objects 의 머리 명사('얼음을 쪼는 검은 새' → 새). 배경에도 나오는 말(자작나무 껍질)은 뺀다."""
    bg = ' '.join(b for b in (row.get('backgrounds') or []) if isinstance(b, str))
    heads = set()
    for o in row.get('objects') or []:
        if isinstance(o, str) and o.strip():
            words = re.sub(r'\(.*?\)', '', o).split()   # '(냉동액)' 처럼 괄호뿐이면 빈 목록
            if words and words[-1] not in bg:
                heads.add(words[-1])
    return heads


def moist_from(row):
    """장면 글 → [{kind, name, src}]. 한 종류는 한 번만(첫 근거)."""
    heads = object_heads(row)
    obj_re = [re.compile(re.escape(h) + JOSA) for h in heads]
    # 글 단위 = (글, 오브제를 확인할 범위). 배경 항목은 확인하지 않는다(None).
    # 본문 문장은 앞 문장까지 본다 — '김이 걷힌 자리마다…'처럼 주어(표지)가 앞 문장에만 있는 경우가 있다(장면 4)
    units = [(b, None) for b in (row.get('backgrounds') or []) if isinstance(b, str)]
    story = row.get('story') if isinstance(row.get('story'), str) else ''
    sents = [u.strip() for u in re.split(r'(?<=[.!?。])\s+|\n+', story) if u.strip()]
    units += [(u, (sents[k - 1] if k else '') + ' ' + u) for k, u in enumerate(sents)]
    out = []
    for kind, name, words, need in MOIST_RULES:
        if MOIST_NOUN[kind] in heads:                      # ① 2팀이 이 물기를 오브제로 적었다
            continue
        for text, scope in units:
            if not any(w in text for w in words):
                continue
            if scope is not None and need and not any(w in text for w in need):
                continue
            if scope is not None and any(r.search(scope) for r in obj_re):   # ② 오브제가 주어인 문장
                continue
            out.append({"kind": kind, "name": name, "src": text})
            break
    return out


def by_convention(num, exts, base_dir):
    """파일명 약속으로 찾기 — input/storyboard/scene_01.png, scene_01.mp3 …

       2팀 스토리보드에는 파일명이 없다. 배경 이미지는 우리가 만들어 넣을 것이므로
       이름을 우리가 정한다. 사운드도 같은 약속으로 넣으면 짝지어진다."""
    for ext in exts:
        name = 'scene_%02d%s' % (num, ext)
        if os.path.exists(os.path.join(base_dir, name)):
            return name
    return None


def to_scene(i, n, row, base_dir):
    """입력 레코드 한 줄 → 프론트가 요구하는 규격 한 줄.

       두 규격을 한 함수로 받는다.
         · 더미(옛 규격)  act · scene_file · sound_file · stage · title · emotion · intensity
         · 2팀 스토리보드  scene · story · backgrounds · objects · emotions[] · physics_laws · vector
       프론트는 image_url / sound_url 만 본다. 파일명을 URL 로 바꾸는 일과
       빠진 칸을 메우는 일이 여기서 끝나야, 프론트에 방어 코드가 안 쌓인다."""
    num = row['_num'] if '_num' in row else scene_number(row, i)
    img = (row.get('scene_file') or row.get('image_file') or row.get('image')
           or by_convention(num, IMAGE_EXT, base_dir))
    snd = (row.get('sound_file') or row.get('audio_file') or row.get('sound')
           or by_convention(num, sorted(AUDIO_EXT), base_dir))

    # 막 — 2팀은 stage 를 따로 주지 않는다. 합의(0917)가 '기승전결 4장면'이므로 순서로 나눈다.
    # 예전엔 i*4//6 으로 6장면을 가정했는데, 4장면이면 기·기·승·승 이 되어 전·결이 사라진다.
    stage = row.get('stage') or row.get('단계')
    if stage not in ACT_KEYS:
        stage = ACT_KEYS[min(3, i * 4 // max(1, n))]

    # 감정 — ① 2팀 main_emotion(1팀 7종, 세기 포함) ② 옛 규격 emotion(더미) ③ 자유 문장에서 짐작
    emo, m_inten = main_emotion(row)
    emo_src = '2팀 대표 감정(main_emotion)' if emo else None
    if emo and emo not in EMO_SEVEN:
        # 7종 밖의 라벨(내용이 매번 달라 '불안'·'경외' 같은 말이 올 수 있다) → 같은 낱말 표로 7종에 붙인다.
        # 못 붙이면 그대로 넘긴다 — 프론트가 영어 라벨은 받고, 모르는 말은 중립 + '(미정의)'로 드러낸다.
        mapped, _ = label_from_phrases([emo])
        if mapped:
            emo, emo_src = mapped, '2팀 대표 감정 "%s" → %s' % (emo, mapped)
    if not emo:
        m_inten = None          # 라벨 없는 세기는 짐작한 라벨에 붙이지 않는다 — 2팀이 그 라벨에 준 세기가 아니다
    if not emo:
        emo = row.get('emotion') or row.get('감정') or None
    if not emo and row.get('emotions'):
        emo, emo_src = label_from_phrases(row.get('emotions'))
    try:
        inten = float(m_inten if m_inten is not None else row.get('intensity', 1.0))
    except (TypeError, ValueError):
        inten = 1.0
    # ※ vector(4개 숫자)는 쓰지 않는다 — 2팀이 장면 요소 추출에 쓰는 내부값이라 제외해 달라고 답했다(09-27).
    #   감정 세기로 오해해 쓰면 없는 값을 지어내는 것.

    backgrounds = [b for b in (row.get('backgrounds') or []) if isinstance(b, str)]
    aw, ab = artist_weights(row)
    laws, n_laws = laws_from(row)
    moist = moist_from(row)
    # 제목 — 2팀은 title 이 없다. 첫 배경 묘사를 쓴다: 우리가 그리는 것이 바로 배경이라,
    # '장면 1' 보다 화면과 이야기의 연결(피드백 7번)을 직접 보여준다. 2팀의 말 그대로다.
    title = (row.get('title') or row.get('제목') or (backgrounds[0] if backgrounds else None)
             or (os.path.splitext(img)[0] if img else '장면 %d' % num))

    # 파일이 실제로 있는지 여기서 본다. 팀 간 인계에서 제일 흔한 사고가 파일명 불일치인데,
    # 그냥 넘기면 브라우저가 조용히 앞 장면을 띄운 채로 제목만 바뀌어 원인을 찾기 어렵다.
    missing = []
    if img and not os.path.exists(os.path.join(base_dir, os.path.basename(img))):
        missing.append(os.path.basename(img))
    if snd and not os.path.exists(os.path.join(base_dir, os.path.basename(snd))):
        missing.append(os.path.basename(snd))
        snd = None                                # 없는 사운드는 아예 넘기지 않는다

    return {
        "act":         num,
        "stage":       stage,                     # 기 / 승 / 전 / 결 — 프론트의 물리 엔진이 이걸로 갈린다
        "title":       title,
        "image_url":   '/media/' + os.path.basename(img) if img else None,
        "sound_url":   '/sound/' + os.path.basename(snd) if snd else None,
        "emotion":     emo,                       # 렌더링·사운드의 보조 가중치. 없으면 프론트가 중립으로 둔다
        "emotion_src": emo_src,                   # 2팀 원문 중 라벨의 근거가 된 문장 — 패널에 그대로 보인다
        "intensity":   max(0.0, min(1.0, inten)), # 감정 세기 — 가중치가 걸리는 깊이
        "backgrounds": backgrounds or None,       # 2팀 배경 묘사 — 시스템 I 의 실제 입력
        "artists":     aw or None,                # 참조 작가 가중치 — 아피찻퐁 외 3명 (없으면 아피찻퐁만)
        "artist_basis": ab or None,               # 그 가중치를 부른 낱말 — 패널에 드러낸다
        "laws":        laws or None,              # 꿈의 물리 법칙 → 엔진 효과 (근거 문장 포함). 없으면 막 물리 그대로
        "laws_total":  n_laws,                    # 2팀이 준 법칙 문장 수 — '몇 개 중 몇 개를 옮겼나'
        "moist":       moist or None,             # 공기 중의 물기(비·눈·서리·김) — 글이 부를 때만, 근거 문장 포함
        "missing":     missing or None,           # 없는 파일 — 프론트가 패널에 드러낸다
    }


def build_scenes():
    """입력을 골라 읽고 → (전체 장면, 그릴 수 있는 장면, 출처 정보)."""
    mode, path, base_dir = pick_source()
    rows = read_scene_list(path) if path else None
    if rows is None:
        rows = normalize_rows(scan_fallback()) if mode == 'dummy' else []
    all_scenes = [to_scene(i, len(rows), r, base_dir) for i, r in enumerate(rows)]
    drawable = [s for s in all_scenes if s['image_url'] and not
                (s['missing'] and os.path.basename(s['image_url']) in s['missing'])]
    info = {
        "mode":     mode,
        "file":     os.path.relpath(path, BASE_DIR).replace('\\', '/') if path else None,
        "total":    len(all_scenes),
        "drawable": len(drawable),
        # 그릴 이미지가 없는 장면 — 어떤 파일명을 기다리는지까지 알려준다
        "waiting":  [{"act": s['act'], "title": s['title'], "expect": 'scene_%02d.png' % s['act']}
                     for s in all_scenes if s not in drawable],
    }
    return all_scenes, drawable, info


def media_dir():
    """/media · /sound 가 파일을 꺼낼 폴더 — 지금 입력 모드를 따른다."""
    return pick_source()[2]


@app.route('/')
def index():
    # 같은 출처에서 열어야 브라우저가 캔버스 픽셀을 읽게 해준다(오염된 캔버스 방지).
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/api/scenes')
def api_scenes():
    """서사 — 입력 JSON 을 프론트 규격으로 옮긴다.

       순서는 act(더미) / scene(2팀) 을 따른다. 배열 순서와 번호가 다를 수 있으므로
       여기서 한 번 정렬해 두면, 프론트는 받은 순서를 믿고 쓰면 된다."""
    all_scenes, scenes, info = build_scenes()
    print("입력: %s (%s)" % (info['file'] or '없음',
                            '2팀 스토리보드' if info['mode'] == 'storyboard' else '더미 기준 자료'))

    # 조용히 넘어가지 않는다 — 그릴 이미지가 없으면 터미널에 크게 남긴다.
    # 예전엔 이미지 없는 장면을 걸러낸 뒤 '0장면 전달' 한 줄만 찍어서, 화면이 왜 캄캄한지 알 수 없었다.
    if info['waiting']:
        where = 'input/storyboard/' if info['mode'] == 'storyboard' else 'input/dummy/'
        print("\n  ⚠ 배경 이미지가 없어 그리지 못하는 장면 %d/%d:" % (len(info['waiting']), info['total']))
        for w in info['waiting']:
            print("     %d. %s → %s%s 필요" % (w['act'], w['title'], where, w['expect']))
        print("     (텍스트 → 배경 이미지 생성 단계가 채울 자리입니다)\n")
    broken = [(s['title'], s['missing']) for s in scenes if s.get('missing')]
    if broken:
        print("\n  ⚠ 입력이 가리키는 파일이 폴더에 없습니다:")
        for title, names in broken:
            print("     %s → %s" % (title, ', '.join(names)))
        print("     (파일명을 맞추거나 JSON 을 고쳐 주세요)\n")
    quiet = [s['title'] for s in scenes if not s['sound_url']]
    if quiet:
        print("사운드가 없는 장면: " + ', '.join(quiet))
    labeled = sum(1 for s in all_scenes if s['emotion'])
    print("스토리 %d장면 중 %d장면 전달 (감정 라벨 %d개)" % (info['total'], len(scenes), labeled))
    return jsonify(scenes)


@app.route('/api/source')
def api_source():
    """지금 어떤 입력으로 돌고 있는가 — 패널 표시와 측정 도구의 모드 확인용.

       /api/scenes 는 그릴 수 있는 장면만 준다(프론트가 이미지 없는 장면을 받으면 앞 장면이 남는다).
       그래서 '읽기는 했지만 못 그리는 장면'은 여기서 따로 알려준다."""
    all_scenes, _, info = build_scenes()
    info['scenes'] = [{"act": s['act'], "stage": s['stage'], "title": s['title'],
                       "emotion": s['emotion'], "emotion_src": s['emotion_src'],
                       "backgrounds": s['backgrounds']} for s in all_scenes]
    return jsonify(info)


@app.route('/api/apichatpong')
def api_apichatpong():
    """아피찻퐁 참조 DB — 유전 알고리즘 적합도의 기준값.

       kickthemachine.com(작가 공식 사이트)에서 영화 스틸·설치 이미지만 골라낸 51장의 색·명암 통계를
       기승전결 4개 군집으로 나눠둔 것. 만드는 절차는 db/build_apichatpong_db.py.
       파일이 없어도 프론트가 내장 대비값으로 도니까 404 로 조용히 넘긴다."""
    path = os.path.join(DB_DIR, 'apichatpong_db.json')
    if not os.path.exists(path):
        print("apichatpong_db.json 이 없습니다 — 프론트가 내장값으로 돕니다.")
        return jsonify({"error": "no db"}), 404
    with open(path, encoding='utf-8') as f:
        return Response(f.read(), mimetype='application/json; charset=utf-8')


@app.route('/api/export', methods=['POST'])
def api_export():
    """프론트가 보낸 장면 대표 프레임을 output/<run>/ 에 저장한다.

       파일 이름·폴더 이름은 서버가 정한다 — 브라우저가 보낸 문자열을 경로로 그대로 쓰지 않는다.
       scenes.json 은 장면이 올 때마다 다시 써서, 도중에 꺼도 그때까지의 목록이 남는다."""
    j = request.get_json(silent=True) or {}
    run = ''.join(ch for ch in str(j.get('run', '')) if ch.isalnum() or ch in '-_')[:60]
    try:
        act = int(j.get('act'))
    except (TypeError, ValueError):
        return jsonify({"error": "act"}), 400
    if not run or not (0 < act < 1000):
        return jsonify({"error": "run/act"}), 400
    d = os.path.join(OUTPUT_DIR, run)
    os.makedirs(d, exist_ok=True)
    saved = []
    for key, suffix in (('png_bg', ''), ('png_title', '_title')):
        data = j.get(key) or ''
        if not data.startswith('data:image/png;base64,'):
            continue
        name = 'scene_%02d%s.png' % (act, suffix)
        with open(os.path.join(d, name), 'wb') as f:
            f.write(base64.b64decode(data.split(',', 1)[1]))
        saved.append(name)
    meta_path = os.path.join(d, 'scenes.json')
    try:
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {"run": run, "scenes": []}
    m = dict(j.get('meta') or {})
    m.update({"act": act, "files": {"background": 'scene_%02d.png' % act,
                                     "with_title": 'scene_%02d_title.png' % act}})
    meta["scenes"] = sorted([x for x in meta.get("scenes", []) if x.get("act") != act] + [m],
                            key=lambda x: x.get("act", 0))
    meta.update(j.get('run_meta') or {})
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("내보내기: output/%s/ %s" % (run, ', '.join(saved)))
    return jsonify({"saved": saved, "dir": 'output/' + run})


def _vint(b, i, keep_marker=False):
    """EBML 가변 길이 정수 → (값, 다음 위치, 바이트 수). 첫 바이트의 앞자리 0 개수가 길이다."""
    first = b[i]
    n = 1
    while n <= 8 and not (first & (0x80 >> (n - 1))):
        n += 1
    v = first if keep_marker else first & ((0x80 >> (n - 1)) - 1)
    for k in range(1, n):
        v = (v << 8) | b[i + k]
    return v, i + n, n


def fix_webm_duration(path, seconds):
    """브라우저 MediaRecorder 가 만든 webm 에 재생 길이(Duration)를 써 넣는다 (09-28).

       MediaRecorder 는 녹화하면서 조각을 흘려보내 끝 길이를 모르므로 Duration 을 비워 둔다.
       그대로 두면 플레이어에 길이가 안 뜨고 앞뒤로 넘기기(탐색)가 안 되며, Unity 등이 길이를 못 읽는다.
       ffmpeg 없이 고치려고 Segment > Info 에 Duration 요소 하나만 덧붙인다.
       실패하면 원본을 그대로 둔다 — 길이가 없어도 재생은 된다."""
    b = open(path, 'rb').read()
    try:
        _, i, _ = _vint(b, 0, True)                   # EBML 헤더
        size, i, _ = _vint(b, i)
        i += size
        seg_id, i, _ = _vint(b, i, True)
        if seg_id != 0x18538067:
            return False
        seg_size_at = i
        seg_size, i, seg_n = _vint(b, i)
        while i < len(b):
            eid, j, _ = _vint(b, i, True)
            esz, k, _ = _vint(b, j)
            if eid == 0x1549A966:                      # Info
                content = b[k:k + esz]
                scale, p = 1000000, 0
                while p < len(content):
                    cid, q, _ = _vint(content, p, True)
                    csz, r, _ = _vint(content, q)
                    if cid == 0x4489:                  # 이미 있다
                        return True
                    if cid == 0x2AD7B1:
                        scale = int.from_bytes(content[r:r + csz], 'big')
                    p = r + csz
                dur = struct.pack('>d', seconds * 1e9 / scale)
                new = content + b'\x44\x89\x88' + dur  # Duration · float64
                size8 = b'\x01' + len(new).to_bytes(7, 'big')
                out = b[:j] + size8 + new + b[k + esz:]
                unknown = (1 << (7 * seg_n)) - 1
                if seg_size != unknown:                # 크기를 아는 Segment 면 늘어난 만큼 고친다
                    grow = len(out) - len(b)
                    v = seg_size + grow
                    head = (0x80 >> (seg_n - 1)) << (8 * (seg_n - 1))
                    out = out[:seg_size_at] + (head | v).to_bytes(seg_n, 'big') + out[seg_size_at + seg_n:]
                with open(path, 'wb') as f:
                    f.write(out)
                return True
            i = k + esz
    except (IndexError, ValueError):
        pass
    return False


@app.route('/api/export_video', methods=['POST'])
def api_export_video():
    """[녹화] 버튼으로 찍은 한 바퀴 영상을 output/<run>/dream.webm 에 저장한다 (09-28).

       영상은 수십 MB 라 base64 JSON 이 아니라 multipart 로 받는다(부풀지 않게).
       video.json 에 장면별 시작 시각을 함께 남긴다 — 4팀이 장면 전환에 맞춰 자를 수 있게."""
    run = ''.join(ch for ch in str(request.form.get('run', '')) if ch.isalnum() or ch in '-_')[:60]
    f = request.files.get('video')
    if not run or f is None:
        return jsonify({"error": "run/video"}), 400
    d = os.path.join(OUTPUT_DIR, run)
    os.makedirs(d, exist_ok=True)
    f.save(os.path.join(d, 'dream.webm'))
    try:
        meta = json.loads(request.form.get('meta') or '{}')
    except ValueError:
        meta = {}
    try:
        dur = float(meta.get('duration_sec') or 0)
    except (TypeError, ValueError):
        dur = 0
    fixed = dur > 0 and fix_webm_duration(os.path.join(d, 'dream.webm'), dur)
    meta.update({"run": run, "file": "dream.webm", "duration_written": bool(fixed)})
    with open(os.path.join(d, 'video.json'), 'w', encoding='utf-8') as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=1)
    mb = os.path.getsize(os.path.join(d, 'dream.webm')) / 1048576
    print("녹화 저장: output/%s/dream.webm (%.1fMB)" % (run, mb))
    return jsonify({"saved": ["dream.webm", "video.json"], "dir": 'output/' + run})


# ── [영상 mp4] 프레임 고정 녹화 (09-29) ────────────────────────────
# 왜: 실시간 [녹화]는 벽시계로 찍는데, 엔진은 '프레임 수'로 장면을 넘긴다. 09-29 발표용 녹화에서
#   이 컴퓨터가 초당 5~19프레임밖에 못 그려 40초짜리가 3분 58초 슬로모션이 됐다(전 장면 5fps).
#   그래서 브라우저가 한 프레임을 그릴 때마다 JPEG 한 장을 보내고, 여기서 60fps mp4 로 잇는다
#   — 컴퓨터가 느려도 결과는 정확히 장면당 10초. 소리는 담지 않는다(이번 발표는 무음, 2팀 답).
# 인코더 (둘 다 이 기능에만 쓴다 — 없으면 이 버튼만 안내를 띄우고 나머지는 flask 만으로 돈다):
#   ① ffmpeg(imageio-ffmpeg 가 들고 오는 실행 파일) — 받은 JPEG 를 그대로 흘려 넣어 libx264 crf 18 로 인코딩.
#      녹화하는 동안 인코딩이 끝나 기다릴 게 없다.
#   ② 없으면 OpenCV. 단 이 PC 의 OpenCV 는 H.264 를 윈도우 내장 인코더(MSMF)로만 쓰고 품질 설정을 무시해
#      40초가 375MB(약 78Mbps)였다(09-29 실측 — 품질 30 을 줘도 같은 크기). 같은 영상을 x264 crf 18 로 다시
#      누르면 55MB · PSNR 44.4dB(눈으로 차이 없음). crf 20 은 45MB 였으나 파편·필름 입자가 잔결이라 한 단계 여유.
#      OpenCV 코덱: avc1 → 안 열리면 mp4v.
try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = None
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
FIXREC = {}                      # run → 쓰는 중인 영상 하나
FIXREC_LOCK = threading.Lock()
X264 = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
# preset: slow 는 40초에 265초가 걸렸다(09-29 재압축). 녹화 중엔 엔진과 CPU 를 나눠 쓴다.
# 10-05: medium → veryfast. 75초 장면이 되며 기록 시간이 문제가 됐다 — 1496×840 단독 실측 medium 16.5fps ·
#        veryfast 47fps(같은 crf 18, 용량 +30%). 엔진(초당 20~30프레임)보다 느린 인코더는 기록을 붙잡는다.


@app.route('/api/fixrec/start', methods=['POST'])
def api_fixrec_start():
    if FFMPEG is None and cv2 is None:
        return jsonify({"error": "인코더가 없습니다 — pip install imageio-ffmpeg"}), 501
    j = request.get_json(silent=True) or {}
    run = ''.join(ch for ch in str(j.get('run', '')) if ch.isalnum() or ch in '-_')[:60]
    w, h, fps = int(j.get('width') or 0), int(j.get('height') or 0), int(j.get('fps') or 60)
    if not run or w < 16 or h < 16:
        return jsonify({"error": "run/width/height"}), 400
    d = os.path.join(OUTPUT_DIR, run)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, 'dream.mp4')
    # 10-05: 브라우저가 무엇을 보내나(pix) — 녹화 속도 실측(헤드리스 · 같은 노트북 Iris Xe):
    #   'h264' 브라우저 하드웨어 인코더(WebCodecs)가 이미 압축한 H.264 → 여기선 mp4 로 감싸기만(-c copy). 초당 약 23프레임
    #   'rgba' 픽셀 그대로 → ffmpeg 가 압축. 초당 약 10프레임 (WebCodecs 가 없는 브라우저용)
    #   'jpeg' 옛 방식(09-29) — 크롬 toBlob 이 '한가할 때' 인코딩해 한 장 1.2~1.8초 대기 → 초당 2.5~7프레임
    pix = j.get('pix') if j.get('pix') in ('h264', 'rgba') else 'jpeg'
    if pix == 'h264' and not FFMPEG:
        return jsonify({"error": "h264 를 mp4 로 감쌀 ffmpeg 가 없습니다 — pip install imageio-ffmpeg"}), 501
    r = {"w": w, "h": h, "fps": fps, "next": 0, "pending": {}, "lock": threading.Lock(), "dir": d, "pix": pix}
    if FFMPEG:
        r["log"] = open(os.path.join(d, 'ffmpeg.log'), 'wb')   # stderr 를 PIPE 로 두면 차서 멈출 수 있다
        if pix == 'h264':
            cmd = ['-f', 'h264', '-framerate', str(fps), '-i', '-', '-c:v', 'copy', '-movflags', '+faststart']
            r["codec"] = 'h264 (브라우저 하드웨어 인코더 WebCodecs · %s)' % (j.get('enc') or '?')
        else:
            src = ['-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', '%dx%d' % (w, h)] if pix == 'rgba' else ['-f', 'image2pipe', '-c:v', 'mjpeg']
            cmd = src + ['-framerate', str(fps), '-i', '-', '-vf', 'scale=%d:%d' % (w, h)] + X264
            r["codec"] = 'h264 (libx264 veryfast crf 18 · %s)' % pix
        r["proc"] = subprocess.Popen([FFMPEG, '-y', '-v', 'error'] + cmd + [path],
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=r["log"])
    else:
        for cc in ('avc1', 'mp4v'):
            vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*cc), fps, (w, h))
            if vw.isOpened():
                break
            vw.release()
        else:
            return jsonify({"error": "mp4 인코더를 열 수 없습니다"}), 500
        r["vw"], r["codec"] = vw, cc + ' (OpenCV — 용량 큼)'
    with FIXREC_LOCK:
        FIXREC[run] = r
    print("영상(mp4) 시작: output/%s/dream.mp4 (%s, %dx%d)" % (run, r["codec"], w, h))
    return jsonify({"ok": True, "codec": r["codec"]})


@app.route('/api/fixrec/frame', methods=['POST'])
def api_fixrec_frame():
    """프레임 한 장(JPEG 원본 바이트). 브라우저가 여러 장을 동시에 보내 순서가 섞일 수 있어
       번호(i)로 줄을 세워 빈 번호가 채워질 때까지 기다렸다가 차례로 쓴다."""
    run = request.args.get('run', '')
    try:
        i = int(request.args.get('i', ''))
    except ValueError:
        return jsonify({"error": "i"}), 400
    r = FIXREC.get(run)
    if r is None:
        return jsonify({"error": "시작되지 않은 녹화"}), 404
    data = request.get_data()
    if r["pix"] == 'rgba':
        if len(data) != r["w"] * r["h"] * 4:
            return jsonify({"error": "픽셀 크기가 다름 (%d바이트)" % len(data)}), 400
    elif r["pix"] == 'jpeg' and not data.startswith(b'\xff\xd8'):
        return jsonify({"error": "JPEG 가 아님"}), 400
    if "vw" in r and r["pix"] == 'rgba':
        data = cv2.cvtColor(np.frombuffer(data, np.uint8).reshape(r["h"], r["w"], 4), cv2.COLOR_RGBA2BGR)
    elif "vw" in r:                          # OpenCV 는 픽셀로 풀어서 넣는다
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return jsonify({"error": "프레임 해석 실패"}), 400
        if img.shape[1] != r["w"] or img.shape[0] != r["h"]:
            img = cv2.resize(img, (r["w"], r["h"]))
        data = img
    with r["lock"]:
        r["pending"][i] = data
        try:
            while r["next"] in r["pending"]:
                x = r["pending"].pop(r["next"])
                if "vw" in r:
                    r["vw"].write(x)
                else:
                    r["proc"].stdin.write(x)     # ffmpeg 가 밀리면 여기서 막힌다 → 브라우저 쪽 fixBusy 가 엔진을 세운다
                r["next"] += 1
        except (BrokenPipeError, OSError):
            return jsonify({"error": "ffmpeg 가 멈췄습니다 — output/%s/ffmpeg.log" % run}), 500
    return jsonify({"ok": True})


@app.route('/api/fixrec/end', methods=['POST'])
def api_fixrec_end():
    j = request.get_json(silent=True) or {}
    run = str(j.get('run', ''))
    with FIXREC_LOCK:
        r = FIXREC.pop(run, None)
    if r is None:
        return jsonify({"error": "시작되지 않은 녹화"}), 404
    enc_err = None
    with r["lock"]:
        lost = len(r["pending"])            # 앞 번호가 끝내 안 온 프레임 — 0 이어야 정상
        if "vw" in r:
            r["vw"].release()
        else:
            try:
                r["proc"].stdin.close()
            except OSError:
                pass
            if r["proc"].wait() != 0:
                enc_err = 'ffmpeg 종료 코드 %d — ffmpeg.log 참조' % r["proc"].returncode
            r["log"].close()
            logp = os.path.join(r["dir"], 'ffmpeg.log')
            if not enc_err and os.path.getsize(logp) == 0:
                os.remove(logp)              # 오류가 없으면 빈 기록은 남기지 않는다
    meta = j.get('meta') or {}
    meta.update({"run": run, "file": "dream.mp4", "codec": r["codec"], "frames_written": r["next"],
                 "frames_lost": lost, "duration_sec": round(r["next"] / float(r["fps"]), 2)})
    if enc_err:
        meta["encoder_error"] = enc_err
    with open(os.path.join(r["dir"], 'video.json'), 'w', encoding='utf-8') as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=1)
    mp4 = os.path.join(r["dir"], 'dream.mp4')
    mb = os.path.getsize(mp4) / 1048576 if os.path.exists(mp4) else 0
    print("영상(mp4) 저장: output/%s/dream.mp4 (%d프레임 · %.1f초 · %.1fMB%s%s)" % (
        run, r["next"], r["next"] / float(r["fps"]), mb, (' · 빠진 프레임 %d' % lost) if lost else '',
        (' · ' + enc_err) if enc_err else ''))
    if enc_err:
        return jsonify({"error": enc_err}), 500
    return jsonify({"saved": ["dream.mp4", "video.json"], "dir": 'output/' + run,
                    "frames": r["next"], "lost": lost, "mb": round(mb, 1)})


@app.route('/api/artists')
def api_artists():
    """PDF 참조 작가 3명 DB — 디갈라카스 · 폰타나 · 마에다 신조 (db/build_artist_db.py).
       없으면 404 — 프론트는 아피찻퐁만으로 예전처럼 돈다."""
    path = os.path.join(DB_DIR, 'artist_db.json')
    if not os.path.exists(path):
        print("artist_db.json 이 없습니다 — 아피찻퐁만으로 돕니다.")
        return jsonify({"error": "no db"}), 404
    with open(path, encoding='utf-8') as f:
        return Response(f.read(), mimetype='application/json; charset=utf-8')


@app.route('/media/<name>')
def media(name):
    return send_from_directory(media_dir(), os.path.basename(name))


@app.route('/sound/<name>')
def sound(name):
    """사운드 — 변환하지 않고 그대로 흘려보낸다.

       conditional=True 여야 브라우저가 Range 요청으로 탐색·루프를 할 수 있다.
       (예전 avi_to_aac 는 통째로 메모리에 올려 보내서 탐색이 안 됐다)
       크롬이 못 읽는 컨테이너(.avi 등)는 여기서 막는다 — 조용히 무음이 되는 대신
       415 로 드러나게 해서, 데이터 포맷이 어긋난 걸 바로 알 수 있게 한다."""
    name = os.path.basename(name)
    ext = os.path.splitext(name)[1].lower()
    if ext not in AUDIO_EXT:
        print("브라우저가 재생할 수 없는 포맷입니다: %s (1·2팀에 .mp3 요청)" % name)
        return "unsupported audio format", 415
    folder = media_dir()
    if not os.path.exists(os.path.join(folder, name)):
        return "not found", 404
    return send_from_directory(folder, name, conditional=True)


if __name__ == '__main__':
    print("\n  꿈의 소산 — http://127.0.0.1:5000  (Ctrl+C 로 종료)")
    print("  입력: %s\n" % ('input/dummy/ (기준 자료, --dummy)' if FORCE_DUMMY else
                          'input/storyboard/ (2팀) — 없으면 input/dummy/.  기준 자료로 돌리려면 --dummy'))
    app.run(port=5000, debug=False)
