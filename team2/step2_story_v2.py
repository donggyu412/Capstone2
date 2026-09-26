# -*- coding: utf-8 -*-
"""
step2_story_v2.py
emotion_peaks.txt → 4개 꿈 장면 생성

[파이프라인]
장면1: emotion_peaks 풀에서 랜덤 뽑기 → 글 생성 → 4D 벡터 추출
장면2~4: 이전 장면 elements에서 Dream Drift + 코사인 유사도 샘플링 → 글 생성

[조정 가능한 값]
- COHERENCE   : 장면 간 연결 강도 (0=꿈처럼 단절, 1=이야기처럼 연결)
- TEMPERATURE : 샘플링 랜덤성 (높을수록 무작위)
- MAX_DRIFT   : 분위기 변화 최대폭
- N_BACKGROUND / N_OBJECT / N_EMOTION : 재료 뽑는 개수
"""
import json
import math
import os
import random
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL_EXTRACT = "claude-haiku-4-5-20251001"
MODEL_STORY   = "claude-sonnet-5"

# ── 재료 뽑는 개수 ───────────────────────────────
N_BACKGROUND = 1
N_OBJECT     = 2
N_EMOTION    = 2

# ── Dream State Machine 파라미터 ─────────────────
COHERENCE   = 0.9   # 0.0 ~ 1.0  (낮을수록 꿈처럼, 높을수록 개연성)
TEMPERATURE = 0.3   # 0.0 ~ 1.0  (낮을수록 알고리즘 주도, 높을수록 랜덤)
MAX_DRIFT   = 0.1   # 0.0 ~ 1.0  (분위기 변화 최대폭)

# 장면 벡터 계산 시 카테고리 가중치
VECTOR_WEIGHTS = {"배경": 0.2, "오브제": 0.5, "감정": 0.3}

# ── 글 품질 검사 기준 ─────────────────────────────
MIN_CHARS    = 500
MAX_CHARS    = 650
TARGET_CHARS = 550
MAX_TRIES    = 3
BANNED       = ["듯한", "듯이", "것 같", "느낌"]
SENTENCE_ENDS = {'.', '!', '?', '…', '"', "'", '”', '’', '」'}

HUMAN_WORDS      = ["사람", "남자", "여자", "아이", "노인"]
HUMAN_WARN_RATIO = 0.4
_HUMAN_SUBJECT_RE = re.compile(
    r"^(?:(?:그녀|그)[는가의]|(?:" + "|".join(HUMAN_WORDS) + r")[은는이가의])"
)

# ── 4D 벡터 축 설명 (Claude에게 전달) ───────────────
VECTOR_AXES = """4개 축의 의미:
- 긴장도 : 0(고요) ~ 1(팽팽)
- 이질감 : 0(현실적) ~ 1(꿈의 논리, 초자연)
- 밀도   : 0(텅 빔, 여백) ~ 1(꽉 참, 빽빽함)
- 온도   : 0(차갑고 날카로움) ~ 1(따뜻하고 물렁함)"""


# ════════════════════════════════════════════════
# 프롬프트
# ════════════════════════════════════════════════

SCENE_PROMPT = """
{이전_장면_컨텍스트}{이전_장면_제약}아래 재료들을 사용해 꿈의 {장면번호}번째 장면을 한국어로 써라. 총 4개의 장면으로 이어지는 연작이다.

[재료]
- 배경: {배경}
- 오브제: {오브제}
- 감정: {감정}

[작성 규칙]
1. 재료 사용
- 모든 재료를 등장시키되 비중은 달라도 된다. 한두 개는 장면의 중심으로, 나머지는 스치듯 배치한다.
- 재료 이름을 그대로 나열하지 말고, 각각 다른 방식(만지기, 소리로 스치기, 멀리 보이기 등)으로 등장시킨다.
- 오브제 중 하나는 장면에서 가장 오래, 가장 자세하게 묘사되는 사물로 둔다.
- 사물을 다시 가리킬 때는 처음 쓴 이름이나 '그것'을 쓴다. "~장치", "~물체"처럼 이름을 돌려 말하는 딱딱한 표현은 쓰지 않는다.

2. 주인공과 시점
- 3인칭 관찰자 시점으로 쓴다. 서술자는 카메라처럼 바깥에서 지켜볼 뿐, 누구의 머릿속에도 들어가지 않는다.
- 이 장면의 주인공은 정해져 있지 않다. 사람, 동물, 기계, 사물, 공간, 빛, 소리, 추상적인 형태 모두 주인공이 될 수 있다.
- 사람은 여러 후보 중 하나일 뿐이다. 사람이 아닌 후보를 먼저 떠올려 보고, 재료가 가장 강하게 요구하는 것을 고른다.
- 생각, 기억, 판단을 서술하지 않는다("생각했다", "깨달았다", "기억했다", "알았다" 금지).
- 사람이 아닌 존재는 사람처럼 말하거나 생각하거나 표정을 짓지 않는다.
- 등장하는 존재는 이름 없이 하나의 호칭으로 통일한다.

3. 꿈의 논리
- 꿈처럼 어긋난 요소를 1~3개 넣는다. 어긋난 요소들은 같은 주제(예: 시간, 무게, 거리)로 묶이게 한다.
- 어긋남은 공간이나 사물에서 일어나게 한다.
- 그 어긋남을 서술자도 등장하는 존재도 설명하거나 의아해하지 않는다.
- '꿈'이라는 단어를 쓰지 않는다.

4. 감정
- 감정을 나타내는 단어(무섭다, 불안하다, 외롭다, 그립다 등)를 쓰지 않는다.
- 감정은 공간과 사물의 상태(소리의 세기, 빛의 흔들림, 온도, 재질의 변화, 움직임)로 전달한다.
- 감정이 둘 이상이면 서로 다른 사물이나 현상에 나눠 담는다.

5. 문체
- 현재형으로 쓴다.
- "~듯", "~것 같은", "~느낌" 같은 추측·느낌 표현은 어떤 형태로도 쓰지 않는다.
- 같은 종결어미가 3번 연속 나오지 않게 한다. 긴 문장과 짧은 문장을 섞는다.
- 같은 수식어나 의성어를 3번 이상 반복하지 않는다.
- 시각 외의 감각(소리, 냄새, 촉감, 온도 등)을 최소 2개 쓴다.

6. 뻔함 피하기
- 재료를 가장 먼저 떠오르는 방식으로 쓰지 않는다.
- 첫 문장은 배경 설명이 아니라 구체적인 행동, 사물, 소리로 시작한다.

7. 열린 결말
- 결론, 깨달음, 회상으로 닫지 않는다.
- 다음 장면으로 이어질 작은 변화 하나에서 끊듯이 끝낸다.

8. 분량과 출력
- 공백 제외 {목표글자수}자 이상, 6~7문단으로 쓴다. 각 문단은 4문장 이상으로 쓴다.
- 반드시 마지막 문장까지 완결해서 끝낸다.
- 이야기 본문만 출력한다. 제목, 설명, 메타 코멘트 없이.

9. 시각적 구체성
- 배경과 주요 사물은 그림으로 그릴 수 있을 만큼 구체적으로 쓴다. 색, 재질, 크기, 위치, 빛의 방향 중 두세 가지를 함께 밝힌다.
- 존재가 나오면 그 생김새(크기, 색, 재질, 자세) 중 두세 가지도 밝힌다.

10. 공간과 분위기
- 열린 자연(숲, 논, 강, 바다)이나 경계 공간(병원 복도, 폐건물, 국경 지대)이 배경으로 어울리면 적극적으로 쓴다.
- 열기, 습도, 곤충 소리, 빗소리 중 하나 이상을 감각 묘사에 넣는다.
- 유령, 동물령, 기이한 존재가 등장할 때 특별한 일처럼 다루지 않는다. 그냥 거기 있는 것처럼 쓴다.
- 같은 사물이나 장소가 살짝 다른 형태로 다시 나타날 수 있다.
- 피부, 땀, 호흡, 체온 중 하나를 구체적으로 쓴다.

[중요] 공백을 제외한 글자 수가 반드시 {목표글자수}자 이상이어야 한다."""


# ════════════════════════════════════════════════
# 순수 파이썬 수학 헬퍼 (numpy 없음)
# ════════════════════════════════════════════════

def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))

def _norm(v):
    return math.sqrt(sum(x * x for x in v))

def cosine_similarity(a, b):
    n = _norm(a) * _norm(b)
    return _dot(a, b) / n if n > 1e-8 else 0.0

def softmax_weights(scores, temperature):
    t = max(temperature, 1e-6)
    scaled = [s / t for s in scores]
    m = max(scaled)
    exps = [math.exp(s - m) for s in scaled]
    total = sum(exps)
    return [e / total for e in exps]

def random_unit_vector(dim=4):
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = _norm(v)
    return [x / n for x in v] if n > 1e-8 else [1.0] + [0.0] * (dim - 1)

def clip_vector(v, lo=0.0, hi=1.0):
    return [max(lo, min(hi, x)) for x in v]

def weighted_mean_vectors(vectors, weights):
    dim = len(vectors[0])
    total_w = sum(weights)
    result = [0.0] * dim
    for v, w in zip(vectors, weights):
        for i in range(dim):
            result[i] += v[i] * w / total_w
    return result


# ════════════════════════════════════════════════
# Claude API 호출
# ════════════════════════════════════════════════

def extract_elements(client, scene_desc: str, sound: str) -> dict:
    """타임테이블 장면 → 배경/오브제 추출 (장면1 재료용, 벡터 없음)"""
    prompt = f"""아래 장면 설명과 사운드 특성에서 배경과 오브제를 추출해라.

장면 설명: {scene_desc}
사운드 특성: {sound}

[정의]
- 배경: 공간, 장소, 날씨, 시간대, 분위기적 환경
- 오브제: 구체적인 사물이나 요소

[출력 형식 — JSON만 출력]
{{
  "배경": ["항목1", "항목2"],
  "오브제": ["항목1", "항목2"]
}}"""
    message = client.messages.create(
        model=MODEL_EXTRACT, max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = next((b.text for b in message.content if hasattr(b, "text")), "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"JSON 파싱 실패:\n{raw}")
    return json.loads(m.group())


def extract_from_story(client, story: str, max_tries: int = 3) -> dict:
    """완성된 글 → 배경/오브제/감정 + 각 요소의 4D 벡터"""
    prompt = f"""아래 글에서 배경, 오브제, 감정, 물리법칙을 추출하고 각 항목의 분위기를 4D 벡터로 점수화해라.

글:
{story}

{VECTOR_AXES}

[물리법칙 정의]
- 이 글에서 현실과 어긋난 꿈의 논리를 짧게 서술 (예: "거리가 걸어도 좁혀지지 않음", "물체가 위로 떨어짐", "크기가 보는 위치에 따라 바뀜")
- 없으면 빈 배열

[출력 형식 — JSON만 출력, 주석 없이 순수 JSON]
{{
  "배경": [{{"항목": "...", "벡터": [긴장도, 이질감, 밀도, 온도]}}, ...],
  "오브제": [{{"항목": "...", "벡터": [긴장도, 이질감, 밀도, 온도]}}, ...],
  "감정": [{{"항목": "...", "벡터": [긴장도, 이질감, 밀도, 온도]}}, ...],
  "물리법칙": ["법칙1", "법칙2", ...]
}}

모든 벡터 값은 0.0~1.0 사이의 소수로. 문자열 안에 쌍따옴표를 쓰지 않는다."""
    for attempt in range(1, max_tries + 1):
        message = client.messages.create(
            model=MODEL_STORY, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next((b.text for b in message.content if hasattr(b, "text")), "").strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            print(f"  [추출 재시도 {attempt}/{max_tries}] JSON 없음")
            continue
        try:
            return json.loads(m.group())
        except json.JSONDecodeError as e:
            print(f"  [추출 재시도 {attempt}/{max_tries}] JSON 파싱 오류: {e}")
    raise ValueError("extract_from_story: JSON 파싱 최대 재시도 초과")


# ════════════════════════════════════════════════
# Dream State Machine
# ════════════════════════════════════════════════

def compute_scene_vector(elements: dict) -> list:
    """장면 요소 전체의 가중 평균 벡터 계산"""
    all_vectors, all_weights = [], []
    for category, weight in VECTOR_WEIGHTS.items():
        for item in elements.get(category, []):
            v = item.get("벡터")
            if v and len(v) == 4:
                all_vectors.append(v)
                all_weights.append(weight)
    if not all_vectors:
        return [0.5, 0.5, 0.5, 0.5]
    return weighted_mean_vectors(all_vectors, all_weights)


def dream_drift(current_vector: list) -> list:
    """현재 벡터에서 랜덤 방향으로 drift → 다음 장면 목표 벡터"""
    direction = random_unit_vector(4)
    distance  = (1 - COHERENCE) * MAX_DRIFT
    target    = [c + d * distance for c, d in zip(current_vector, direction)]
    return clip_vector(target)


def sample_elements(elements: dict, target_vector: list,
                    excluded_backgrounds: list = None,
                    penalized_objects: set = None) -> tuple:
    """코사인 유사도 기반 가중치 샘플링 → (배경, 오브제, 감정) 리스트"""
    def sample_category(items, n, excluded=None, penalized=None):
        if not items:
            return []

        # 배경: 이전 장면 배경은 후보에서 제외 (fallback: 전부 제외되면 그냥 씀)
        candidates = items
        if excluded:
            filtered = [i for i in items if i["항목"] not in excluded]
            if filtered:
                candidates = filtered

        sims    = [cosine_similarity(item.get("벡터", [0.5]*4), target_vector) for item in candidates]
        weights = softmax_weights(sims, TEMPERATURE)

        # 오브제: 2장면 연속 등장한 항목은 가중치 0.1배 패널티
        if penalized:
            weights = [w * 0.1 if item["항목"] in penalized else w
                       for item, w in zip(candidates, weights)]
            total = sum(weights)
            if total > 1e-8:
                weights = [w / total for w in weights]

        chosen = random.choices(candidates, weights=weights, k=min(n, len(candidates)))
        # 중복 제거
        seen, result = set(), []
        for item in chosen:
            name = item["항목"]
            if name not in seen:
                seen.add(name)
                result.append(name)
        # 부족하면 보충 (패널티 항목 제외 우선)
        if len(result) < n:
            remaining = [i for i in candidates if i["항목"] not in seen]
            extra = random.sample(remaining, min(n - len(result), len(remaining)))
            result += [i["항목"] for i in extra]
        return result

    penalized = penalized_objects or set()
    bg  = sample_category(elements.get("배경",  []), N_BACKGROUND, excluded=excluded_backgrounds)
    obj = sample_category(elements.get("오브제", []), N_OBJECT,    penalized=penalized)
    emo = sample_category(elements.get("감정",  []), N_EMOTION)
    return bg, obj, emo


def build_context(previous_stories: list) -> str:
    """COHERENCE에 따라 이전 장면 컨텍스트 구성"""
    if not previous_stories or COHERENCE < 0.3:
        return ""
    if COHERENCE < 0.7:
        last_para = previous_stories[-1].strip().split("\n\n")[-1]
        return f"[직전 장면 마지막 문단]\n{last_para}\n\n"
    context = ""
    for i, story in enumerate(previous_stories, 1):
        context += f"[장면 {i}]\n{story}\n\n"
    return context


# ════════════════════════════════════════════════
# 글 검사 및 생성
# ════════════════════════════════════════════════

def count_no_space(text: str) -> int:
    return len(re.sub(r"\s", "", text))

def human_subject_ratio(story: str) -> tuple:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", story) if s.strip()]
    if not sentences:
        return 0, 0, 0.0
    human = sum(1 for s in sentences if _HUMAN_SUBJECT_RE.match(s))
    return human, len(sentences), human / len(sentences)

def check_story(story: str, truncated: bool = False) -> list:
    problems = []
    n = count_no_space(story)
    if n < MIN_CHARS:
        problems.append(f"분량이 부족하다({n}자). 공백 제외 {TARGET_CHARS}자 이상으로 쓸 것.")
    if n > MAX_CHARS:
        problems.append(f"분량이 너무 길다({n}자). 공백 제외 {TARGET_CHARS}자 안팎으로 줄일 것.")
    hits = [w for w in BANNED if w in story]
    if hits:
        problems.append(f"금지 표현이 들어 있다: {hits}. 이 표현 없이 단정적으로 쓸 것.")
    if truncated or (story and story.rstrip()[-1] not in SENTENCE_ENDS):
        problems.append("글이 문장 중간에서 끊겼다. 마지막 문장까지 완결해서 쓸 것.")
    return problems


def generate_scene(client, scene_num: int,
                   backgrounds: list, objects: list, emotions: list,
                   previous_stories: list,
                   used_physics: list = None,
                   previous_backgrounds: list = None) -> str:
    context = build_context(previous_stories)

    # 이전 장면 물리법칙/배경 금지 구성
    if used_physics or previous_backgrounds:
        lines = ["[이전 장면에서 이미 사용한 것 — 이번 장면에서 반복 금지]"]
        if used_physics:
            lines.append(f"- 초현실 물리 법칙: {', '.join(used_physics)}")
        if previous_backgrounds:
            lines.append(f"- 배경 공간: {', '.join(previous_backgrounds)}")
        lines.append("→ 위 법칙과 배경은 이번 장면에 쓰지 않는다. 새로운 공간과 새로운 꿈의 어긋남을 만들어라.")
        prev_constraint = "\n".join(lines) + "\n\n"
    else:
        prev_constraint = ""

    base_prompt = SCENE_PROMPT.format(
        이전_장면_컨텍스트=context,
        이전_장면_제약=prev_constraint,
        장면번호=scene_num,
        배경=", ".join(backgrounds),
        오브제=", ".join(objects),
        감정=", ".join(emotions),
        목표글자수=TARGET_CHARS,
    )
    prompt = base_prompt
    best_story, best_problems = "", None

    for attempt in range(1, MAX_TRIES + 1):
        message = client.messages.create(
            model=MODEL_STORY, max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        story     = next((b.text for b in message.content if hasattr(b, "text")), "").strip()
        truncated = message.stop_reason == "max_tokens"
        if truncated:
            print("  ※ max_tokens에 걸려 글이 잘렸습니다.")

        problems = check_story(story, truncated)
        if not problems:
            return story

        print(f"  [재시도 {attempt}/{MAX_TRIES}] {problems}")
        if best_problems is None or len(problems) <= len(best_problems):
            best_story, best_problems = story, problems

        prompt = (
            base_prompt
            + "\n\n[직전 초안]\n" + story
            + "\n\n[직전 초안의 문제점]\n" + "\n".join(f"- {p}" for p in problems)
            + "\n\n위 초안을 바탕으로 문제를 고쳐서 처음부터 끝까지 다시 써라. "
              "분량이 부족하면 문단을 추가해 장면을 더 길게 펼쳐라."
        )

    print("  ※ 재시도 횟수를 모두 사용했습니다. 문제가 가장 적은 결과를 사용합니다.")
    return best_story


# ════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════

def main(input_path: str = "team2/output/parsed_scenes.json",
         output_dir: str = "team2/output"):

    scenes = json.loads(Path(input_path).read_text(encoding="utf-8"))
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    out    = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ── 장면1 재료: emotion_peaks 풀에서 추출 ──────────────
    all_bg, all_obj, all_emo = [], [], []
    print(f"[추출] {len(scenes)}개 타임테이블에서 요소 추출 중...")
    for scene in scenes:
        elements = extract_elements(client, scene["설명"], scene["사운드"])
        all_bg.extend(elements.get("배경",  []))
        all_obj.extend(elements.get("오브제", []))
        all_emo.extend([
            e.strip()
            for e in scene["감정"].replace("(", ",").replace(")", ",").split(",")
            if e.strip()
        ])

    all_bg  = list(dict.fromkeys(all_bg))
    all_obj = list(dict.fromkeys(all_obj))
    all_emo = list(dict.fromkeys(all_emo))

    print(f"  배경 후보 {len(all_bg)}개: {all_bg}")
    print(f"  오브제 후보 {len(all_obj)}개: {all_obj}")
    print(f"  감정 후보 {len(all_emo)}개: {all_emo}")

    previous_stories         = []
    current_vector           = None
    all_used_physics         = []
    all_previous_backgrounds = []   # 프롬프트 금지용 (샘플링된 배경 이름)
    all_prev_bg_names        = []   # 샘플링 제외용 (elements 항목 이름)
    object_history           = []   # 장면별 오브제 집합 (패널티 계산용)

    for scene_num in range(1, 5):
        print(f"\n{'═'*50}")
        print(f"  장면 {scene_num} 생성")
        print(f"{'═'*50}")

        # ── 재료 선택 ──────────────────────────────────────
        if scene_num == 1:
            bg  = random.sample(all_bg,  min(N_BACKGROUND, len(all_bg)))
            obj = random.sample(all_obj, min(N_OBJECT,     len(all_obj)))
            emo = random.sample(all_emo, min(N_EMOTION,    len(all_emo)))
        else:
            # 이전 장면 elements에서 Dream Drift + 코사인 샘플링
            prev_elements_path = out / f"scene{scene_num-1}_elements.json"
            prev_elements = json.loads(prev_elements_path.read_text(encoding="utf-8"))
            target_vector = dream_drift(current_vector)

            print(f"  현재 벡터: {[round(x, 2) for x in current_vector]}")
            print(f"  목표 벡터: {[round(x, 2) for x in target_vector]}")

            # 2장면 연속 등장한 오브제 → 패널티
            penalized_obj = set()
            if len(object_history) >= 2:
                penalized_obj = object_history[-1] & object_history[-2]

            bg, obj, emo = sample_elements(
                prev_elements, target_vector,
                excluded_backgrounds=all_prev_bg_names if all_prev_bg_names else None,
                penalized_objects=penalized_obj if penalized_obj else None,
            )

        print(f"  배경: {bg}")
        print(f"  오브제: {obj}")
        print(f"  감정: {emo}")

        # ── 글 생성 ────────────────────────────────────────
        print(f"\n[생성] 장면{scene_num} 글 작성 중...")
        story = generate_scene(
            client, scene_num, bg, obj, emo, previous_stories,
            used_physics=all_used_physics if all_used_physics else None,
            previous_backgrounds=all_previous_backgrounds if all_previous_backgrounds else None,
        )

        # ── 저장 ───────────────────────────────────────────
        story_path = out / f"scene{scene_num}_story.txt"
        story_path.write_text(story, encoding="utf-8")

        n = count_no_space(story)
        print(f"\n  저장 → {story_path} (공백 제외 {n}자)")

        h, total, ratio = human_subject_ratio(story)
        print(f"  [참고] 사람이 주어인 문장: {h}/{total} ({ratio:.0%})")
        if ratio > HUMAN_WARN_RATIO:
            print("  [참고] 사람 중심 쏠림이 높습니다.")

        print(f"\n{'─'*40}")
        print(story)
        print(f"{'─'*40}")

        # ── elements + 벡터 추출 ───────────────────────────
        print(f"\n[벡터 추출] 장면{scene_num} 요소 분석 중...")
        elements = extract_from_story(client, story)
        elements_path = out / f"scene{scene_num}_elements.json"
        elements_path.write_text(json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8")

        # 각 카테고리 출력
        for cat in ("배경", "오브제", "감정"):
            items = elements.get(cat, [])
            print(f"  {cat}: {[i['항목'] for i in items]}")

        physics = elements.get("물리법칙", [])
        if physics:
            print(f"  물리법칙: {physics}")
            all_used_physics.extend(physics)

        # 배경 금지 목록 누적
        all_previous_backgrounds.extend(bg)
        all_prev_bg_names.extend(item["항목"] for item in elements.get("배경", []))

        # 오브제 히스토리 누적 (패널티 계산용)
        object_history.append(set(item["항목"] for item in elements.get("오브제", [])))

        # ── 현재 벡터 갱신 ─────────────────────────────────
        current_vector = compute_scene_vector(elements)
        print(f"  장면{scene_num} 벡터: {[round(x, 2) for x in current_vector]}")

        previous_stories.append(story)

    print(f"\n{'═'*50}")
    print("  4개 장면 생성 완료")
    print(f"{'═'*50}")
    for i in range(1, 5):
        print(f"  scene{i}_story.txt / scene{i}_elements.json")

    # ── 전체 결과 단일 JSON으로 취합 ───────────────────
    export = []
    for i in range(1, 5):
        story_text = (out / f"scene{i}_story.txt").read_text(encoding="utf-8")
        elem       = json.loads((out / f"scene{i}_elements.json").read_text(encoding="utf-8"))
        export.append({
            "scene": i,
            "story": story_text,
            "backgrounds": [e["항목"] for e in elem.get("배경",  [])],
            "objects":     [e["항목"] for e in elem.get("오브제", [])],
            "emotions":    [e["항목"] for e in elem.get("감정",  [])],
            "physics_laws": elem.get("물리법칙", []),
            "vector":      [round(x, 3) for x in compute_scene_vector(elem)],
        })

    export_path = out / "dream_scenes.json"
    export_path.write_text(
        json.dumps({"scenes": export}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n  취합 완료 → {export_path}")


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "team2/output/parsed_scenes.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "team2/output"
    main(inp, out)
