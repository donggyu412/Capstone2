# -*- coding: utf-8 -*-
"""
step2_story_v2.py
4개 타임테이블 → 배경/오브제/감정 리스트 추출 → 랜덤 뽑기 → 장면1 글 생성

[조정 가능한 값]
"""
import json
import os
import random
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL_EXTRACT = "claude-haiku-4-5-20251001"  # 추출용 (빠르고 저렴)
MODEL_STORY   = "claude-sonnet-5"            # 글 생성용 (고품질)

# ────────────────────────────────────────────
# 여기서 뽑는 개수를 바꿔가며 테스트하세요
N_BACKGROUND = 2   # 배경 리스트에서 뽑는 개수
N_OBJECT     = 3   # 오브제 리스트에서 뽑는 개수
N_EMOTION    = 2   # 감정 리스트에서 뽑는 개수
# ────────────────────────────────────────────


def extract_elements(client: anthropic.Anthropic, scene_desc: str, sound: str) -> dict:
    """장면설명 + 사운드 → 배경 리스트, 오브제 리스트 추출 (Claude API)"""
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

    import re
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"JSON 파싱 실패:\n{raw}")
    return json.loads(m.group())


def generate_scene1(client: anthropic.Anthropic,
                    backgrounds: list, objects: list, emotions: list) -> str:
    """랜덤으로 뽑은 요소들로 장면1 글 생성"""
    prompt = f"""아래 재료들을 사용해 꿈의 첫 번째 장면을 한국어로 써라.

[재료]
- 배경: {', '.join(backgrounds)}
- 오브제: {', '.join(objects)}
- 감정: {', '.join(emotions)}

[작성 규칙]
- 위 재료들을 반드시 글 속에 녹여 쓰되, 꼭 주 요소는 될 필요 없이 참고 요소로 사용해도 된다. 직접 나열하지 말고 자연스럽게 스며들게 해라.
- 문장과 문장이 너무 부자연스럽지 않게 하나의 장면 안에서 자연스럽게 이어지는 스토리로 작성한다.
- 이야기는 특정 형식이나 장르에 제한되지 않고 자유롭게 전개한다.
- 감정을 직접 서술하지 마라. 감각과 분위기로만 전달해라.
- 결말을 짓지 마라. 열린 채로 끝나야 한다.
- 공백 제외 600자 이상 써라.
- 이야기 본문만 출력한다. 메타 설명 없이."""

    message = client.messages.create(
        model=MODEL_STORY,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return next((b.text for b in message.content if hasattr(b, "text")), "").strip()


def main(input_path: str = "output/parsed_scenes.json", output_dir: str = "output"):
    scenes = json.loads(Path(input_path).read_text(encoding="utf-8"))
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # 1. 4개 타임테이블에서 배경/오브제/감정 전부 수집
    all_backgrounds, all_objects, all_emotions = [], [], []

    print(f"[추출] {len(scenes)}개 타임테이블에서 요소 추출 중...")
    for scene in scenes:
        elements = extract_elements(client, scene["설명"], scene["사운드"])
        all_backgrounds.extend(elements.get("배경", []))
        all_objects.extend(elements.get("오브제", []))

        emotion_tags = [e.strip() for e in scene["감정"].replace("(", ",").replace(")", ",").split(",") if e.strip()]
        all_emotions.extend(emotion_tags)

    print(f"  배경 후보 {len(all_backgrounds)}개: {all_backgrounds}")
    print(f"  오브제 후보 {len(all_objects)}개: {all_objects}")
    print(f"  감정 후보 {len(all_emotions)}개: {all_emotions}")

    # 2. 랜덤 뽑기
    picked_bg  = random.sample(all_backgrounds, min(N_BACKGROUND, len(all_backgrounds)))
    picked_obj = random.sample(all_objects,     min(N_OBJECT,     len(all_objects)))
    picked_emo = random.sample(all_emotions,    min(N_EMOTION,    len(all_emotions)))

    print(f"\n[랜덤 선택]")
    print(f"  배경 ({N_BACKGROUND}개): {picked_bg}")
    print(f"  오브제 ({N_OBJECT}개): {picked_obj}")
    print(f"  감정 ({N_EMOTION}개): {picked_emo}")

    # 3. 장면1 글 생성
    print("\n[생성] 장면1 글 작성 중...")
    story = generate_scene1(client, picked_bg, picked_obj, picked_emo)

    # 4. 저장
    out = Path(output_dir)
    out.mkdir(exist_ok=True)
    out_path = out / "scene1_story.txt"
    out_path.write_text(story, encoding="utf-8")
    print(f"\n장면1 저장 완료 → {out_path} ({len(story)}자)")
    print("\n" + "─" * 40)
    print(story)
    print("─" * 40)

    return story


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "output/parsed_scenes.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "output"
    main(inp, out)
