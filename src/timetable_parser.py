"""
타임테이블 파서 (v2) — 사운드/장면설명/내레이션이 각각 초 단위(소수점 포함)로
쪼개져 있고, 내레이션은 문장 단위로 타임스탬프가 붙어있는 새 포맷 전용.

포맷 예:
    장면# : S01
    사운드 : 얼음소리 | 00:00.00 - 00:09.90 (9.90초)
      두꺼운 얼음이 갈라지는 소리...
    장면 설명 : 00:00.00 - 00:09.90
      냉동 수면 캡슐 안에서...
    내레이션 : 00:00.00 - 00:09.38
      00:00.00 - 00:02.11  "얼음이 갈라지는 소리에 깨어났다."
      00:02.11 - 00:04.07  "냉동 수면 캡슐 안쪽이다."
    ------------------------------------------------------------------------
"""

import re


TIME_RE = r"\d{1,2}:\d{2}(?:\.\d+)?"

SCENE_RE = re.compile(
    r"장면#\s*:\s*(?P<scene>\S+)\s*\n"
    r"사운드\s*:\s*(?P<sound_label>.+?)\s*\|\s*"
    r"(?P<sound_start>" + TIME_RE + r")\s*-\s*(?P<sound_end>" + TIME_RE + r")\s*\([^)]*\)\s*\n"
    r"(?P<sound_desc>.*?)\n"
    r"장면 설명\s*:\s*(?P<desc_start>" + TIME_RE + r")\s*-\s*(?P<desc_end>" + TIME_RE + r")\s*\n"
    r"(?P<description>.*?)\n"
    r"내레이션\s*:\s*(?P<narr_start>" + TIME_RE + r")\s*-\s*(?P<narr_end>" + TIME_RE + r")\s*\n"
    r"(?P<sentences_block>(?:[ \t]*" + TIME_RE + r"\s*-\s*" + TIME_RE + r"\s+\".*?\"\s*\n?)+)",
    re.DOTALL,
)

SENTENCE_RE = re.compile(
    r"(?P<start>" + TIME_RE + r")\s*-\s*(?P<end>" + TIME_RE + r")\s+\"(?P<text>.*?)\""
)


def parse_time(ts: str) -> float:
    """'01:23.62' -> 83.62 형태로 변환 (분:초.소수초)"""
    m, s = ts.split(":")
    return int(m) * 60 + float(s)


def parse_timetable(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    scenes = []
    for match in SCENE_RE.finditer(content):
        sentences = []
        for sm in SENTENCE_RE.finditer(match.group("sentences_block")):
            sentences.append({
                "start_sec": parse_time(sm.group("start")),
                "end_sec": parse_time(sm.group("end")),
                "text": sm.group("text").strip(),
            })

        scenes.append({
            "scene": match.group("scene").strip(),
            "sound_label": match.group("sound_label").strip(),
            "sound_start": parse_time(match.group("sound_start")),
            "sound_end": parse_time(match.group("sound_end")),
            "sound_desc": match.group("sound_desc").strip(),
            "desc_start": parse_time(match.group("desc_start")),
            "desc_end": parse_time(match.group("desc_end")),
            "description": match.group("description").strip(),
            "narr_start": parse_time(match.group("narr_start")),
            "narr_end": parse_time(match.group("narr_end")),
            "sentences": sentences,
            # 장면 전체의 시간 범위 = 사운드 시작 ~ 사운드 끝 (장면 경계로 사용)
            "start_sec": parse_time(match.group("sound_start")),
            "end_sec": parse_time(match.group("sound_end")),
        })

    if not scenes:
        raise ValueError(
            "타임테이블에서 장면을 하나도 찾지 못했습니다. "
            "포맷(장면# / 사운드 / 장면 설명 / 내레이션 + 문장별 타임스탬프)이 "
            "원본과 다른지 확인해주세요."
        )
    return scenes
