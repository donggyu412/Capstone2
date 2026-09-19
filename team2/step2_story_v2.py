# -*- coding: utf-8 -*-
"""
step2_story_v2.py
4개 타임테이블 → 배경/오브제/감정 리스트 추출 → 랜덤 뽑기 → 장면1 글 생성

주인공(시선이 가장 오래 머무는 대상)은 코드가 정하지 않고 모델이 재료를 보고 자유롭게 고른다.
다만 모델이 습관적으로 사람을 고르는 경향이 있어, 프롬프트에서 그 쏠림만 풀어준다.

[조정 가능한 값]
- N_BACKGROUND / N_OBJECT / N_EMOTION : 랜덤으로 뽑는 재료 개수
- MIN_CHARS / MAX_CHARS / TARGET_CHARS : 분량 기준 (통과 하한 / 상한 / 프롬프트에 요청하는 목표)
- MAX_TRIES                            : 재시도 횟수
- BANNED                               : 금지 표현 목록
- HUMAN_WORDS / HUMAN_WARN_RATIO       : 사람 중심으로 쓰였는지 참고용으로 알려주는 기준 (재생성은 하지 않음)
- SCENE1_PROMPT                        : 장면1 글 생성 프롬프트
"""
import json
import os
import random
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL_EXTRACT = "claude-haiku-4-5-20251001"  # 추출용 (빠르고 저렴)
MODEL_STORY   = "claude-sonnet-5"            # 글 생성용 (고품질)

# ────────────────────────────────────────────
# 여기서 뽑는 개수를 바꿔가며 테스트하세요
N_BACKGROUND = 1   # 배경 리스트에서 뽑는 개수
N_OBJECT     = 2   # 오브제 리스트에서 뽑는 개수
N_EMOTION    = 2   # 감정 리스트에서 뽑는 개수
# ────────────────────────────────────────────

# ────────────────────────────────────────────
# 검사 기준 (통과하지 못하면 재생성)
MIN_CHARS    = 700    # 공백 제외, 이 미만이면 재생성
MAX_CHARS    = 1400   # 공백 제외, 이 초과면 재생성
TARGET_CHARS = 1000   # 프롬프트에 요청하는 목표 (모델은 요청보다 짧게 쓰는 경향이 있어 높게 잡음)
MAX_TRIES    = 3
BANNED       = ["듯한", "듯이", "것 같", "느낌"]

# 참고용 지표 (재생성에 쓰지 않고 결과만 알려줌)
HUMAN_WORDS      = ["사람", "남자", "여자", "아이", "노인"]
HUMAN_WARN_RATIO = 0.4

# 문장 끝으로 인정하는 문자
SENTENCE_ENDS = {'.', '!', '?', '…', '"', "'", '”', '’', '」'}

_HUMAN_SUBJECT_RE = re.compile(
    r"^(?:(?:그녀|그)[는가의]|(?:" + "|".join(HUMAN_WORDS) + r")[은는이가의])"
)
# ────────────────────────────────────────────

SCENE1_PROMPT = """아래 재료들을 사용해 꿈의 첫 번째 장면을 한국어로 써라. 이 장면은 4개로 이어지는 연작 꿈의 시작이다.

[재료]
- 배경: {배경}
- 오브제: {오브제}
- 감정: {감정}

[작성 규칙]
1. 재료 사용
- 모든 재료를 등장시키되 비중은 달라도 된다. 한두 개는 장면의 중심으로, 나머지는 스치듯 배치한다.
- 재료 이름을 그대로 나열하지 말고, 각각 다른 방식(만지기, 소리로 스치기, 멀리 보이기 등)으로 등장시킨다.
- 오브제 중 하나는 장면에서 가장 오래, 가장 자세하게 묘사되는 사물로 둔다. 이 사물은 이후 장면에서 다시 쓰인다.
- 사물을 다시 가리킬 때는 처음 쓴 이름이나 '그것'을 쓴다. "~장치", "~물체"처럼 이름을 돌려 말하는 딱딱한 표현은 쓰지 않는다.

2. 주인공과 시점
- 3인칭 관찰자 시점으로 쓴다. 서술자는 카메라처럼 바깥에서 지켜볼 뿐, 누구의 머릿속에도 들어가지 않는다.
- 이 장면의 주인공(시선이 가장 오래 머무는 대상)은 정해져 있지 않다. 재료를 보고 가장 자연스럽게 중심이 될 만한 것을 직접 고른다. 사람, 동물, 기계, 사물, 공간 자체, 빛이나 소리 같은 현상, 선이나 형태 같은 추상적인 것 모두 주인공이 될 수 있다.
- 사람은 여러 후보 중 하나일 뿐이다. 글을 쓰기 전에 사람이 아닌 후보(공간, 사물, 동물, 기계, 현상, 추상적인 형태)를 먼저 떠올려 보고, 재료가 가장 강하게 요구하는 것을 주인공으로 고른다. 사람이 가장 자연스러울 때만 사람을 고른다. 사람이 아예 나오지 않는 장면도 좋다.
- 생각, 기억, 판단을 서술하지 않는다("생각했다", "깨달았다", "기억했다", "알았다" 금지).
- 직업, 사연, 이 장소에 온 이유는 설명하지 않는다.
- 사람이 아닌 존재가 나올 때는 사람처럼 말하거나 생각하거나 표정을 짓지 않는다. 그 존재 고유의 방식(움직임, 소리, 자세, 형태의 변화)으로만 행동한다.
- 등장하는 존재는 이름 없이 하나의 호칭으로 통일한다. 사람이면 '그', '그녀', '아이', '노인' 등을 쓰고, 사람이 아니면 종류 이름('로봇', '고양이' 등)이나 '그것'을 쓴다. 존재가 나오는 경우, 있는 위치와 지닌 것을 문단마다 일관되게 쓰고, 사물을 다루는 동작(집기, 내려놓기 등)을 빠뜨리지 않는다.

3. 꿈의 논리
- 하나의 공간과 시간 안에서 장면이 이어지게 쓰되, 꿈처럼 어긋난 요소를 1~3개 넣는다. 어긋난 요소들은 서로 같은 주제(예: 시간, 무게, 거리)로 묶이게 한다.
- 어긋남은 공간이나 사물에서 일어나게 한다(사물이 스스로 움직이거나, 공간의 규칙이 맞지 않는 식).
- 그 어긋남을 서술자도 등장하는 존재도 설명하거나 의아해하지 않는다. "~하는데도", "여전히", "이미"처럼 어긋남을 짚는 말 없이 사실로만 적는다.
- '꿈'이라는 단어를 쓰지 않는다.

4. 감정
- 감정을 나타내는 단어(무섭다, 불안하다, 외롭다, 그립다 등)를 쓰지 않는다.
- 감정은 공간과 사물의 상태(소리의 세기, 빛의 흔들림, 온도, 재질의 변화, 사물의 움직임)로 전달한다. 사람이나 동물, 기계 같은 존재가 나오는 경우에만 그 존재의 몸짓, 소리, 움직임(사람이면 표정, 호흡, 손의 움직임)을 함께 쓸 수 있다.
- 감정이 둘 이상이면 서로 다른 사물이나 현상에 나눠 담는다. 하나가 짧게 스치는 정도여도 되지만, 둘 다 반드시 보여야 한다.

5. 문체
- 현재형으로 쓴다. 서술자는 지금 벌어지는 일을 지켜보듯 쓴다.
- "~듯", "~것 같은", "~느낌" 같은 추측·느낌 표현은 어떤 형태로도 쓰지 않는다. 단정적으로 쓴다.
- 같은 종결어미가 3번 연속 나오지 않게 한다. 긴 문장과 짧은 문장을 섞는다.
- 같은 수식어나 의성어를 장면 안에서 3번 이상 반복하지 않는다.
- 시각 외의 감각(소리, 냄새, 촉감, 온도 등)을 최소 2개 쓴다.

6. 뻔함 피하기
- 재료를 가장 먼저 떠오르는 방식으로 쓰지 않는다. 예상 밖의 쓰임을 고른다.
- 첫 문장은 배경 설명이 아니라 구체적인 행동, 사물, 소리로 시작한다.

7. 열린 결말
- 결론, 깨달음, 회상으로 닫지 않는다. 잠에서 깨는 것으로도 끝내지 않는다.
- "여전히 ~하고 있었다"처럼 같은 상태가 계속된다는 문장으로도 끝내지 않는다.
- 다음 장면으로 이어질 작은 변화 하나(무언가 시작되거나, 발견되거나, 바뀌는 순간)에서 끊듯이 끝낸다.

8. 분량과 출력
- 공백 제외 {목표글자수}자 이상, 6~7문단으로 쓴다. 각 문단은 4문장 이상으로 쓴다.
- 반드시 마지막 문장까지 완결해서 끝낸다.
- 이야기 본문만 출력한다. 제목, 설명, 메타 코멘트 없이.

9. 시각적 구체성
- 배경과 주요 사물은 그림으로 그릴 수 있을 만큼 구체적으로 쓴다. 색, 재질, 크기, 위치, 빛의 방향 중 두세 가지를 함께 밝힌다.
- 존재가 나오면 그 존재의 생김새(크기, 색, 재질, 자세) 중 두세 가지도 함께 밝힌다.
- 눈에 띄는 배경은 하나, 주요 사물은 2~4개 정도로 정리한다. 사물을 지나치게 늘리지 않는다.

[중요] 공백을 제외한 글자 수가 반드시 {목표글자수}자 이상이어야 한다. 쓰다가 짧아질 것 같으면 문단을 더 늘려서라도 채워라."""


def extract_elements(client: anthropic.Anthropic, scene_desc: str, sound: str) -> dict:
    prompt = f"""아래 장면 설명과 사운드 특성에서 배경과 오브제를 추출해라.

장면 설명: {scene_desc}
사운드 특성: {sound}

[정의]
- 배경: 공간, 장소, 날씨, 시간대, 분위기적 환경 (예: 새벽 안개, 빈 플랫폼, 어두운 터널)
- 오브제: 장면 설명과 사운드 특성 모두에서 등장하는 구체적인 사물이나 요소 (예: 시계탑, 젖은 타일, 기차, 물방울 소리)

[출력 형식 — JSON만 출력, 다른 텍스트 없이]
{{
  "배경": ["항목1", "항목2", ...],
  "오브제": ["항목1", "항목2", ...]
}}"""
    message = client.messages.create(
        model=MODEL_EXTRACT,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = next((b.text for b in message.content if hasattr(b, "text")), "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"JSON 파싱 실패:\n{raw}")
    return json.loads(m.group())


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


def extract_from_story(client: anthropic.Anthropic, story: str) -> dict:
    """완성된 글에서 배경/오브제/감정 전부 추출"""
    prompt = f"""아래 글에서 배경, 오브제, 감정을 모두 추출해라.

글:
{story}

[정의]
- 배경: 공간, 장소, 날씨, 시간대, 분위기적 환경
- 오브제: 글에 등장하는 구체적인 사물, 소리, 현상 (작은 것도 포함)
- 감정: 글에서 느껴지는 감정이나 분위기 (단어로 직접 쓰이지 않아도, 공간과 사물의 상태에서 읽히는 것 포함)

[출력 형식 — JSON만 출력, 다른 텍스트 없이]
{{
  "배경": ["항목1", "항목2", ...],
  "오브제": ["항목1", "항목2", ...],
  "감정": ["항목1", "항목2", ...]
}}"""
    message = client.messages.create(
        model=MODEL_STORY,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = next((b.text for b in message.content if hasattr(b, "text")), "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"JSON 파싱 실패:\n{raw}")
    return json.loads(m.group())


def generate_scene1(client: anthropic.Anthropic,
                    backgrounds: list, objects: list, emotions: list) -> str:
    base_prompt = SCENE1_PROMPT.format(
        배경=", ".join(backgrounds),
        오브제=", ".join(objects),
        감정=", ".join(emotions),
        목표글자수=TARGET_CHARS,
    )
    prompt = base_prompt
    best_story, best_problems = "", None

    for attempt in range(1, MAX_TRIES + 1):
        message = client.messages.create(
            model=MODEL_STORY,
            max_tokens=8192,
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
              "분량이 부족하면 문단을 추가해 장면을 더 길게 펼쳐라. 초안의 좋은 표현은 살려도 된다."
        )

    print("  ※ 재시도 횟수를 모두 사용했습니다. 문제가 가장 적은 결과를 사용합니다.")
    return best_story


def main(input_path: str = "team2/output/parsed_scenes.json", output_dir: str = "team2/output"):
    scenes = json.loads(Path(input_path).read_text(encoding="utf-8"))
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    all_backgrounds, all_objects, all_emotions = [], [], []

    print(f"[추출] {len(scenes)}개 타임테이블에서 요소 추출 중...")
    for scene in scenes:
        elements = extract_elements(client, scene["설명"], scene["사운드"])
        all_backgrounds.extend(elements.get("배경", []))
        all_objects.extend(elements.get("오브제", []))

        emotion_tags = [
            e.strip()
            for e in scene["감정"].replace("(", ",").replace(")", ",").split(",")
            if e.strip()
        ]
        all_emotions.extend(emotion_tags)

    all_backgrounds = list(dict.fromkeys(all_backgrounds))
    all_objects     = list(dict.fromkeys(all_objects))
    all_emotions    = list(dict.fromkeys(all_emotions))

    print(f"  배경 후보 {len(all_backgrounds)}개: {all_backgrounds}")
    print(f"  오브제 후보 {len(all_objects)}개: {all_objects}")
    print(f"  감정 후보 {len(all_emotions)}개: {all_emotions}")

    picked_bg  = random.sample(all_backgrounds, min(N_BACKGROUND, len(all_backgrounds)))
    picked_obj = random.sample(all_objects,     min(N_OBJECT,     len(all_objects)))
    picked_emo = random.sample(all_emotions,    min(N_EMOTION,    len(all_emotions)))

    print(f"\n[랜덤 선택]")
    print(f"  배경 ({N_BACKGROUND}개): {picked_bg}")
    print(f"  오브제 ({N_OBJECT}개): {picked_obj}")
    print(f"  감정 ({N_EMOTION}개): {picked_emo}")

    print("\n[생성] 장면1 글 작성 중...")
    story = generate_scene1(client, picked_bg, picked_obj, picked_emo)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    out_path = out / "scene1_story.txt"
    out_path.write_text(story, encoding="utf-8")

    meta = {"배경": picked_bg, "오브제": picked_obj, "감정": picked_emo}
    meta_path = out / "scene1_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    n_no_space = count_no_space(story)
    print(f"\n장면1 저장 완료 → {out_path} (공백 포함 {len(story)}자 / 공백 제외 {n_no_space}자)")
    print(f"재료 정보 저장 → {meta_path}")
    if not (MIN_CHARS <= n_no_space <= MAX_CHARS):
        print(f"  ※ 공백 제외 {MIN_CHARS}~{MAX_CHARS}자 범위를 벗어났습니다.")

    h, total, ratio = human_subject_ratio(story)
    print(f"  [참고] 사람이 주어인 문장: {h}/{total} ({ratio:.0%})")
    if ratio > HUMAN_WARN_RATIO:
        print("  [참고] 사람 중심으로 쓰인 장면입니다. 여러 번 돌려서 이 쏠림이 반복되는지 확인해 보세요.")

    print("\n" + "─" * 40)
    print(story)
    print("─" * 40)

    # 5. 완성된 글에서 모든 요소 추출
    print("\n[추출] 완성된 글에서 요소 추출 중...")
    story_elements = extract_from_story(client, story)
    elements_path = out / "scene1_elements.json"
    elements_path.write_text(json.dumps(story_elements, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"글 요소 추출 → {elements_path}")
    print(f"  배경: {story_elements.get('배경', [])}")
    print(f"  오브제: {story_elements.get('오브제', [])}")
    print(f"  감정: {story_elements.get('감정', [])}")

    return story


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "team2/output/parsed_scenes.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "team2/output"
    main(inp, out)
