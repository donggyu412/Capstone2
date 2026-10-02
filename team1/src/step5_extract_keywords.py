# -*- coding: utf-8 -*-
"""
[5단계] 키워드 풀 추출 — 조합/변이는 하지 않고, 재료(키워드)와 공감 정보만 JSON으로 만든다.

입력
  1) emotion_peaks.txt      (step4 결과: 어느 장면에서 관객이 어떤 감정으로 얼마나 공감했는가)
  2) sound_timetable.txt    (「아르카디아」 30장면: 장면 설명 / 나레이션 / 사운드 특성)
  3) keyword_bank.json      (장면별 키워드 뱅크. 없는 장면만 LLM으로 뽑아서 채워 넣음)

출력
  keyword_pool.json         (step6이 읽는 파일: 피크 정보 + 종류별 키워드 풀 + 감정 풀)

동작 순서
  1. 30장면 각각에서 배경 / 사물(엔티티·오브제) / 상태 / 사운드 키워드를 뽑는다.
     - 이미 keyword_bank.json에 있는 장면은 다시 뽑지 않는다 (LLM 호출 0회, 결과 항상 동일).
     - 없는 장면만 LLM(claude 또는 ollama)으로 뽑아 뱅크에 저장한다. 중간에 끊겨도 이어서 가능.
  2. emotion_peaks.txt의 피크가 걸린 장면의 키워드에 그 피크의 공감률을 붙인다.
     (여러 피크가 같은 장면에 걸리면 가장 높은 공감률, 걸리지 않은 장면은 null)
  3. 같은 키워드가 여러 장면에 나오면 하나로 합치고 출처_장면을 리스트로 모은다.
  4. 피크 4개를 골라 기승전결을 배정한다 (기승전결_배정).
     - 4개 선정: 공감률 상위, 같은 감정은 최대 2개
     - 전(절정) = 공감률 1위 / 결 = 공감률 최저(동률이면 시간이 늦은 쪽) / 기·승 = 나머지를 시간순

사용법
    # 뱅크가 이미 있으면 LLM 없이 바로 실행됨
    python step5_extract_keywords.py

    # 뱅크를 LLM(Claude)으로 새로 만들기 (ANTHROPIC_API_KEY 필요)
    python step5_extract_keywords.py --rebuild --llm claude

    # 로컬 Qwen(Ollama)으로 새로 만들기
    python step5_extract_keywords.py --rebuild --llm ollama --model qwen3:8b
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from timetable_parser import parse_timetable

ENTITY_KINDS = ("엔티티", "오브제")
BANNED = ["듯한", "듯이", "것 같", "느낌"]  # 키워드에 추측 표현이 섞이지 않게 거르는 목록

DEFAULT_MODELS = {
    "claude": "claude-haiku-4-5-20251001",   # 추출용: 빠르고 저렴한 모델
    "ollama": "qwen3:8b",                    # 설치된 모델명은 `ollama list`로 확인
}


# ─────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────
def sec_to_mmss(sec):
    m = int(sec) // 60
    s = sec - m * 60
    return f"{m:02d}:{s:05.2f}"


# ─────────────────────────────────────────────────────────
# 1. emotion_peaks.txt 읽기
# ─────────────────────────────────────────────────────────
PEAK_HEAD_RE = re.compile(
    r"\[(\d+)순위\]\s+(\d+:\d+(?:\.\d+)?)\s*-\s*(\d+:\d+(?:\.\d+)?)\s+\(소속 장면:\s*([^)]*)\)"
)
EMOTION_RE = re.compile(r"^감정\s*:\s*(\S+)\s*\((\d+)/(\d+)명,\s*([\d.]+)%\)", re.MULTILINE)
DIST_RE = re.compile(r"^전체 분포\s*:\s*(.+)$", re.MULTILINE)


def parse_peaks(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    is_demo = "DEMO" in text[:300]

    peaks = []
    for block in re.split(r"-{10,}", text):
        head = PEAK_HEAD_RE.search(block)
        if not head:
            continue
        rank = int(head.group(1))
        time_range = f"{head.group(2)}-{head.group(3)}"
        scene_ids = re.findall(r"S\d+", head.group(4))

        emo = EMOTION_RE.search(block)
        if not emo:
            print(f"[경고] {rank}순위 블록에서 감정 줄을 읽지 못했습니다. 건너뜁니다.")
            continue
        emotion, agree, total, pct = emo.group(1), int(emo.group(2)), int(emo.group(3)), float(emo.group(4))

        dist = {}
        dm = DIST_RE.search(block)
        if dm:
            for name, cnt in re.findall(r"(\S+)\s+(\d+)명", dm.group(1)):
                dist[name] = int(cnt)

        # 대표 장면: 나레이션 줄([S16] 02:31.47-...)이 가장 많은 장면, 없으면 소속 장면 중 첫 번째
        counts = Counter(re.findall(r"\[(S\d+)\]\s+\d{1,2}:\d{2}", block))
        if counts:
            main_scene = counts.most_common(1)[0][0]
        else:
            main_scene = scene_ids[0] if scene_ids else None

        peaks.append({
            "순위": rank,
            "장면": main_scene,
            "소속_장면": scene_ids,
            "감정": emotion,
            "공감률": pct,
            "인원": f"{agree}/{total}",
            "시간": time_range,
            "분포": dist,
        })

    peaks.sort(key=lambda p: p["순위"])
    return peaks, is_demo


# ─────────────────────────────────────────────────────────
# 2. 키워드 뱅크 (장면별 키워드)
# ─────────────────────────────────────────────────────────
def _clean_list(items):
    out, seen = [], set()
    for it in items or []:
        s = str(it).strip()
        if not s or s in seen or any(b in s for b in BANNED):
            continue
        seen.add(s)
        out.append(s)
    return out


def normalize_entry(raw):
    """LLM 출력이든 수기 작성이든 같은 모양(배경/사물/상태/사운드)으로 정리"""
    entry = {
        "배경": _clean_list(raw.get("배경")),
        "사물": [],
        "상태": _clean_list(raw.get("상태")),
        "사운드": _clean_list(raw.get("사운드")),
    }
    seen = set()
    for it in raw.get("사물") or []:
        if isinstance(it, dict):
            text = str(it.get("키워드", "")).strip()
            kind = it.get("종류", "오브제")
        else:
            text, kind = str(it).strip(), "오브제"
        if kind not in ENTITY_KINDS:
            kind = "오브제"
        if not text or text in seen or any(b in text for b in BANNED):
            continue
        seen.add(text)
        entry["사물"].append({"키워드": text, "종류": kind})
    return entry


def load_bank(path):
    p = Path(path)
    if not p.exists():
        return {}, {}
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    meta = data.get("_생성정보", {})
    bank = {k: normalize_entry(v) for k, v in data.items() if not k.startswith("_")}
    return bank, meta


def save_bank(path, bank, meta):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = {"_생성정보": meta}
    data.update(bank)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


EXTRACT_PROMPT = """아래는 SF 단편 「아르카디아 : 얼음 속의 방송」의 한 장면 정보다. 이 장면에서 꿈 장면을 만들 재료가 될 키워드를 뽑아라.

[장면 번호] {scene}
[장면 설명] {description}
[나레이션] {narration}
[사운드 이름] {sound_label}
[사운드 특성] {sound_desc}

[뽑을 항목]
- 배경: 이 장면의 공간이나 환경 (0~2개)
- 사물: 장면에 등장하는 구체적인 것 (2~4개). 항목마다 종류를 표시한다.
    "엔티티" = 스스로 움직이거나 행동하는 존재 (사람, 동물, 로봇, 드론 등)
    "오브제" = 그 밖의 사물, 물질, 현상
- 상태: 사물이나 공간의 상태를 나타내는 짧은 수식어 (2~3개). "젖은", "성에가 낀"처럼 관형형으로 쓴다.
- 사운드: 사운드 특성에서 뽑은 소리의 짧은 묘사 (1~3개)

[규칙]
1. 원문에 근거가 있는 것만 뽑는다. 없는 것을 지어내지 않는다.
2. 각 키워드는 2~15자의 짧은 명사구나 수식어로 쓴다.
3. "듯한", "듯이", "것 같", "느낌" 같은 추측 표현을 쓰지 않는다.
4. 감정을 나타내는 단어(무섭다, 슬프다 등)는 키워드로 뽑지 않는다.
5. 해당하는 것이 없으면 빈 리스트로 둔다.

[출력 형식 — JSON만 출력, 다른 텍스트 없이]
{{
  "배경": ["..."],
  "사물": [{{"키워드": "...", "종류": "엔티티"}}, {{"키워드": "...", "종류": "오브제"}}],
  "상태": ["..."],
  "사운드": ["..."]
}}"""


def build_prompt(scene):
    return EXTRACT_PROMPT.format(
        scene=scene["scene"],
        description=" ".join(scene["description"].split()),
        narration=" ".join(s["text"] for s in scene["sentences"]),
        sound_label=scene["sound_label"],
        sound_desc=" ".join(scene["sound_desc"].split()),
    )


def call_llm(prompt, backend, model, ollama_url="http://localhost:11434"):
    if backend == "claude":
        try:
            import anthropic
        except ImportError:
            sys.exit("anthropic 패키지가 없습니다: pip install anthropic")
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    if backend == "ollama":
        try:
            import requests
        except ImportError:
            sys.exit("requests 패키지가 없습니다: pip install requests")
        r = requests.post(
            f"{ollama_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2},
            },
            timeout=300,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    raise ValueError(f"알 수 없는 llm 종류: {backend}")


def extract_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)  # Qwen 등의 사고 과정 제거
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"JSON을 찾지 못했습니다: {text[:100]!r}")
    return json.loads(m.group())


def build_bank(scenes, bank_path, backend, model, rebuild, ollama_url, retries=3):
    bank, meta = ({}, {}) if rebuild else load_bank(bank_path)
    todo = [s for s in scenes if s["scene"] not in bank]

    if not todo:
        print(f"[뱅크] {len(bank)}장면 모두 이미 있음 → LLM 호출 없음 ({bank_path})")
        return bank, meta

    print(f"[뱅크] {len(todo)}장면을 {backend}({model})로 추출합니다.")
    meta = {"방식": f"LLM ({backend})", "모델": model}

    for i, sc in enumerate(todo, 1):
        prompt = build_prompt(sc)
        entry = None
        for attempt in range(1, retries + 1):
            try:
                entry = normalize_entry(extract_json(call_llm(prompt, backend, model, ollama_url)))
                break
            except Exception as e:
                print(f"  [{sc['scene']}] 시도 {attempt}/{retries} 실패: {e}")
        if entry is None:
            save_bank(bank_path, bank, meta)   # 지금까지의 결과는 보존
            sys.exit(f"{sc['scene']} 추출에 실패했습니다. 다시 실행하면 이 장면부터 이어서 진행합니다.")

        if not any(entry.values()):
            print(f"  [경고] {sc['scene']}: 뽑힌 키워드가 하나도 없습니다.")
        bank[sc["scene"]] = entry
        save_bank(bank_path, bank, meta)       # 장면 하나 끝날 때마다 저장 (중단해도 이어서 가능)
        print(f"  [{i}/{len(todo)}] {sc['scene']} 완료")

    return bank, meta


# ─────────────────────────────────────────────────────────
# 3. 키워드 풀 만들기
# ─────────────────────────────────────────────────────────
def _better(new, old):
    return new is not None and (old is None or new > old)


def make_pool(peaks, scenes, bank):
    # 장면별 공감률 (여러 피크가 걸리면 최댓값)
    scene_pct = {}
    for p in peaks:
        for sid in p["소속_장면"]:
            if _better(p["공감률"], scene_pct.get(sid)):
                scene_pct[sid] = p["공감률"]

    pool = {"배경": [], "사물": [], "상태": [], "사운드": [], "감정": []}
    merged = {"배경": {}, "사물": {}, "상태": {}}   # 같은 키워드는 하나로 합침

    def add_merged(cat, text, sid, pct, kind=None):
        found = merged[cat].get(text)
        if found is None:
            item = {"키워드": text}
            if kind:
                item["종류"] = kind
            item["출처_장면"] = [sid]
            item["공감률"] = pct
            merged[cat][text] = item
            pool[cat].append(item)
        else:
            if sid not in found["출처_장면"]:
                found["출처_장면"].append(sid)
            if _better(pct, found["공감률"]):
                found["공감률"] = pct
            if kind == "엔티티":
                found["종류"] = "엔티티"

    for sc in scenes:
        sid = sc["scene"]
        entry = bank.get(sid)
        if not entry:
            continue
        pct = scene_pct.get(sid)

        for text in entry["배경"]:
            add_merged("배경", text, sid, pct)
        for it in entry["사물"]:
            add_merged("사물", it["키워드"], sid, pct, it["종류"])
        for text in entry["상태"]:
            add_merged("상태", text, sid, pct)
        for text in entry["사운드"]:
            pool["사운드"].append({
                "키워드": text,
                "라벨": sc["sound_label"],
                "출처_장면": [sid],
                "구간": f"{sec_to_mmss(sc['sound_start'])}-{sec_to_mmss(sc['sound_end'])}",
                "공감률": pct,
            })

    # 감정 풀: 피크에 나온 감정만, 같은 감정이면 공감률이 높은 피크 기준
    best = {}
    for p in peaks:
        e = p["감정"]
        if e not in best or p["공감률"] > best[e]["공감률"]:
            best[e] = {"키워드": e, "공감률": p["공감률"], "피크_장면": p["장면"], "피크_순위": p["순위"]}
    pool["감정"] = sorted(best.values(), key=lambda x: -x["공감률"])

    return pool


# ─────────────────────────────────────────────────────────
# 4. 기승전결 배정
# ─────────────────────────────────────────────────────────
def _start_sec(time_range):
    m = re.match(r"(\d+):(\d+(?:\.\d+)?)", time_range)
    return int(m.group(1)) * 60 + float(m.group(2)) if m else 0.0


def assign_gisungjeongyeol(peaks, max_same_emotion=2):
    """피크 4개를 골라 기·승·전·결 역할을 배정한다. (랜덤 없음 → 같은 입력이면 항상 같은 결과)

    1) 4개 선정: 공감률 높은 순(동률이면 step4 순위가 앞선 것)으로 고르되,
       같은 감정은 최대 max_same_emotion개, 같은 장면은 1개까지.
    2) 전(절정) = 선정된 4개 중 공감률 1위
    3) 결        = 나머지 중 공감률 최저 (동률이면 시간이 늦은 쪽)
    4) 기, 승    = 남은 2개를 시간순으로 (앞이 기, 뒤가 승)

    반환: (배정 리스트[기,승,전,결 순], 경고 문자열 리스트)
    """
    warnings = []
    cands = sorted((p for p in peaks if p["장면"]), key=lambda p: (-p["공감률"], p["순위"]))

    picked, used_scenes, emo_count = [], set(), Counter()
    for p in cands:
        if len(picked) == 4:
            break
        if p["장면"] in used_scenes or emo_count[p["감정"]] >= max_same_emotion:
            continue
        picked.append(p)
        used_scenes.add(p["장면"])
        emo_count[p["감정"]] += 1

    if len(picked) < 4:  # 감정 제한 때문에 모자라면 제한을 풀어서 채움
        for p in cands:
            if len(picked) == 4:
                break
            if p in picked or p["장면"] in used_scenes:
                continue
            picked.append(p)
            used_scenes.add(p["장면"])
            warnings.append(f"같은 감정 최대 {max_same_emotion}개 제한을 풀어 {p['순위']}순위({p['감정']})를 넣었습니다.")

    if len(picked) < 4:
        warnings.append(f"서로 다른 장면의 피크가 {len(picked)}개뿐이라 기승전결을 배정하지 못했습니다.")
        return [], warnings

    jeon = max(picked, key=lambda p: (p["공감률"], -p["순위"]))
    rest = [p for p in picked if p is not jeon]
    gyeol = min(rest, key=lambda p: (p["공감률"], -_start_sec(p["시간"])))
    mid = sorted((p for p in rest if p is not gyeol), key=lambda p: _start_sec(p["시간"]))
    roles = [("기", mid[0]), ("승", mid[1]), ("전", jeon), ("결", gyeol)]

    return [
        {
            "역할": role,
            "감정": p["감정"],
            "피크_장면": p["장면"],
            "피크_순위": p["순위"],
            "공감률": p["공감률"],
            "인원": p["인원"],
            "시간": p["시간"],
        }
        for role, p in roles
    ], warnings


# ─────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────
def main(args):
    scenes = parse_timetable(args.timetable)
    peaks, is_demo = parse_peaks(args.peaks)
    if not peaks:
        sys.exit("emotion_peaks.txt에서 피크를 하나도 읽지 못했습니다. 파일 형식을 확인하세요.")

    model = args.model or DEFAULT_MODELS[args.llm]
    bank, bank_meta = build_bank(scenes, args.bank, args.llm, model, args.rebuild, args.ollama_url)

    scene_ids = {s["scene"] for s in scenes}
    for p in peaks:
        unknown = [sid for sid in p["소속_장면"] if sid not in scene_ids]
        if unknown:
            print(f"[경고] {p['순위']}순위 피크의 장면 {unknown}이 타임테이블에 없습니다.")
    missing = [s["scene"] for s in scenes if s["scene"] not in bank]
    if missing:
        print(f"[경고] 뱅크에 없는 장면: {missing}")

    pool = make_pool(peaks, scenes, bank)
    assignment, assign_warnings = assign_gisungjeongyeol(peaks)
    for w in assign_warnings:
        print(f"[경고] {w}")

    result = {
        "메타": {
            "입력_피크파일": os.path.basename(args.peaks),
            "입력_타임테이블": os.path.basename(args.timetable),
            "키워드_뱅크": os.path.basename(args.bank),
            "추출방식": bank_meta.get("방식", "뱅크 파일 사용"),
            "데모": is_demo,
            "피크수": len(peaks),
            "장면수": len(scenes),
        },
        "기승전결_배정": assignment,
        "피크": peaks,
        "키워드": pool,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n완료. 저장됨: {out}")
    print(f"  피크 {len(peaks)}개" + (" (데모 데이터)" if is_demo else ""))
    for a in assignment:
        print(f"  {a['역할']}: {a['피크_장면']} {a['감정']} {a['공감률']}% ({a['인원']}, {a['시간']})")
    for cat in ("배경", "사물", "상태", "사운드", "감정"):
        weighted = sum(1 for k in pool[cat] if k.get("공감률") is not None)
        print(f"  {cat}: {len(pool[cat])}개 (공감률 붙은 것 {weighted}개)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="키워드 풀 추출 (조합/변이 없음)")
    ap.add_argument("--peaks", default="../output/emotion_peaks.txt")
    ap.add_argument("--timetable", default="../timetable/sound_timetable.txt")
    ap.add_argument("--bank", default="../output/keyword_bank.json",
                    help="장면별 키워드 뱅크. 있으면 재사용, 없는 장면만 LLM으로 채움")
    ap.add_argument("--output", default="../output/keyword_pool.json")
    ap.add_argument("--llm", choices=["claude", "ollama"], default="claude",
                    help="뱅크에 없는 장면을 뽑을 때 쓸 LLM")
    ap.add_argument("--model", default=None, help="LLM 모델명 (기본: claude는 haiku, ollama는 qwen3:8b)")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--rebuild", action="store_true", help="뱅크를 무시하고 전 장면을 LLM으로 새로 뽑음")
    main(ap.parse_args())