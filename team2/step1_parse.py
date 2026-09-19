# -*- coding: utf-8 -*-
"""타임테이블 txt 파싱 → parsed_scenes.json"""
import json
import re
import sys
from pathlib import Path


def parse_scenes(text):
    # [N순위] 블록 단위로 분리
    blocks = re.split(r"-{10,}", text)
    scenes = []

    for block in blocks:
        block = block.strip()
        if not block or "순위" not in block:
            continue

        # 소속 장면 (S01, S02 ...)
        m_scene = re.search(r"소속 장면:\s*(S\d+)", block)
        num = m_scene.group(1) if m_scene else "?"

        # 감정
        m_emotion = re.search(r"^감정\s*:\s*(\S+)", block, re.MULTILINE)
        emotion = m_emotion.group(1) if m_emotion else ""

        # 나레이션 문장들
        narrations = re.findall(r'"\s*(.+?)\s*"', block)
        narration_text = " ".join(narrations)

        # 사운드 특성 (레이블 뒤 설명 전체)
        m_sound = re.search(r"\[S\d+\]\s+\S+\s*:\s*(.+)", block, re.DOTALL)
        sound = re.sub(r"\s+", " ", m_sound.group(1)).strip() if m_sound else ""

        scenes.append({
            "번호": num,
            "설명": narration_text,
            "사운드": sound,
            "감정": emotion,
        })

    return scenes


def main(timetable_path: str, output_dir: str = "output"):
    text = Path(timetable_path).read_text(encoding="utf-8")
    scenes = parse_scenes(text)
    if not scenes:
        print("오류: 장면을 하나도 파싱하지 못했습니다. 파일 형식을 확인하세요.")
        sys.exit(1)

    out = Path(output_dir)
    out.mkdir(exist_ok=True)
    out_path = out / "parsed_scenes.json"
    out_path.write_text(json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"파싱 완료: {len(scenes)}개 장면 → {out_path}")
    for s in scenes:
        print(f"  장면#{s['번호']}: {s['설명'][:30]}...")
    return scenes


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python step1_parse.py <timetable.txt> [output_dir]")
        sys.exit(1)
    timetable = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    main(timetable, out_dir)
