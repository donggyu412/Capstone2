"""
[추가 단계] 공감 피크 구간 탐지 (v2)

교수님 요구사항 반영:
- 30초 등 고정 장면 단위가 아니라, 관객 공감도가 기준(%)을 넘는 시간대를
  데이터에서 직접 찾아냄
- 그 구간의 "나레이션"과 "감정"을 추출
- 결과가 4~6개가 되도록 기준을 자동으로 조정 (너무 적으면 완화, 너무 많으면 강화)
- 사운드 특성도 함께 기록

문장 단위 매칭:
- 새 타임테이블 포맷(timetable_parser.py)은 내레이션이 문장 단위로 타임스탬프가
  붙어있어서, 피크 구간이 정확히 어느 문장과 겹치는지까지 찾아낼 수 있음

사용법:
    python step4_detect_peaks.py \
        --timetable ../timetable/arcadia.txt \
        --emotion_csv ../output/multi_test.csv \
        --output ../output/emotion_peaks.txt
"""

import argparse
import csv
from collections import Counter, defaultdict

from timetable_parser import parse_timetable


def sec_to_mmss(sec):
    m = int(sec) // 60
    s = sec - m * 60
    return f"{m:02d}:{s:05.2f}"


def load_emotion_rows(csv_path):
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "timestamp_sec": float(row["timestamp_sec"]),
                "face_id": row["face_id"],
                "emotion_kr": row["emotion_kr"],
                "confidence": float(row["confidence"]),
            })
    return rows


def compute_window_score(rows, start, end, exclude_neutral=True):
    in_range = [r for r in rows if start <= r["timestamp_sec"] < end]

    per_face = defaultdict(list)
    for r in in_range:
        per_face[r["face_id"]].append(r["emotion_kr"])

    face_repr = {}
    for face_id, emos in per_face.items():
        face_repr[face_id] = Counter(emos).most_common(1)[0][0]

    total_faces = len(face_repr)
    if total_faces == 0:
        return None

    counts = Counter(face_repr.values())

    if exclude_neutral:
        candidates = {k: v for k, v in counts.items() if k != "중립"}
        if not candidates:
            return None
    else:
        candidates = counts

    emotion, agree = max(candidates.items(), key=lambda x: x[1])

    return {
        "start": start,
        "end": end,
        "emotion": emotion,
        "agree_count": agree,
        "total_faces": total_faces,
        "agree_pct": round(agree / total_faces * 100, 1),
        "breakdown": dict(counts),
    }


def scan_windows(rows, window_size, step, duration, exclude_neutral, min_agree, min_pct):
    windows = []
    t = 0.0
    while t < duration:
        w = compute_window_score(rows, t, t + window_size, exclude_neutral)
        if w and w["agree_count"] >= min_agree and w["agree_pct"] >= min_pct:
            windows.append(w)
        t += step
    return windows


def select_non_overlapping(windows, min_gap):
    """공감률(%) 내림차순으로, 서로 min_gap 이내로 겹치는 건 건너뛰며 최대한 뽑음
    (공감률이 같으면 공감 인원이 많은 쪽 우선)"""
    ranked = sorted(windows, key=lambda w: (w["agree_pct"], w["agree_count"]), reverse=True)
    selected = []
    for w in ranked:
        overlaps = any(
            not (w["end"] <= s["start"] - min_gap or w["start"] >= s["end"] + min_gap)
            for s in selected
        )
        if not overlaps:
            selected.append(w)
    return selected


STRONG_PCT = 50.0   # 이 공감률 미만으로 뽑힌 피크는 '약한 피크'로 표시


def find_peaks_targeting_count(rows, window_size, step, duration, exclude_neutral,
                                min_gap, target_low, target_high,
                                pct_start=95.0, pct_decay=5.0,
                                base_min_agree=2):
    """
    결과 개수가 target_low~target_high(예: 4~6개) 안에 들어오도록 기준을 단계적으로 완화.

      1단계: 공감 비율 기준을 95%에서 5%씩 낮춤 (50% 아래로도 계속, 0%까지)
      2단계: 그래도 부족하면 피크 사이 최소 간격(min_gap)을 절반 → 0초로 줄임
      3단계: 그래도 부족하면 최소 공감 인원(min_agree)을 1명으로 낮춤

    같은 조건에서 target_high보다 많이 나오면 상위 target_high개만 취한다.
    반환: (선정된 피크, 마지막으로 쓴 공감 비율 기준, 완화 내역 리스트)
    """
    def attempt(pct, gap, agree):
        windows = scan_windows(rows, window_size, step, duration,
                               exclude_neutral, agree, pct)
        return select_non_overlapping(windows, gap)

    best = ([], pct_start, base_min_agree, min_gap)

    def done(selected, pct, agree, gap):
        notes = []
        if pct < STRONG_PCT:
            notes.append(f"공감 비율 기준을 {STRONG_PCT:g}% 미만({pct:g}%)까지 낮춤")
        if gap < min_gap:
            notes.append(f"피크 최소 간격 {min_gap:g}초 → {gap:g}초")
        if agree < base_min_agree:
            notes.append(f"최소 공감 인원 {base_min_agree}명 → {agree}명")
        return selected[:target_high], pct, notes

    # 1단계: 공감 비율 기준 낮추기
    pct = pct_start
    while pct >= 0:
        selected = attempt(pct, min_gap, base_min_agree)
        if len(selected) >= target_low:
            return done(selected, pct, base_min_agree, min_gap)
        if len(selected) > len(best[0]):
            best = (selected, pct, base_min_agree, min_gap)
        pct = round(pct - pct_decay, 6)

    # 2단계: 최소 간격 줄이기 / 3단계: 최소 인원 낮추기 (공감 비율 기준은 0%)
    for gap, agree in [(min_gap / 2, base_min_agree), (0.0, base_min_agree), (0.0, 1)]:
        if gap >= min_gap and agree >= base_min_agree:
            continue
        selected = attempt(0.0, gap, agree)
        if len(selected) >= target_low:
            return done(selected, 0.0, agree, gap)
        if len(selected) > len(best[0]):
            best = (selected, 0.0, agree, gap)

    # 모든 완화 후에도 부족 (중립 제외 후 반응이 거의 없는 데이터 등)
    selected, pct, agree, gap = best
    if not selected:   # 아무것도 못 찾았으면 끝까지 완화한 상태로 보고
        pct, agree, gap = 0.0, 1, 0.0
    return done(selected, pct, agree, gap)


def find_sentence_matches(peak, scenes):
    matches = []
    for sc in scenes:
        if not (peak["start"] < sc["end_sec"] and peak["end"] > sc["start_sec"]):
            continue
        for sent in sc["sentences"]:
            if peak["start"] < sent["end_sec"] and peak["end"] > sent["start_sec"]:
                matches.append({"scene": sc["scene"], **sent})
    return matches


def match_scenes(peak, scenes):
    return [sc for sc in scenes if peak["start"] < sc["end_sec"] and peak["end"] > sc["start_sec"]]


def format_output(peaks, scenes, pct_used, target_low, target_high, relax_notes=None):
    lines = []
    lines.append("=" * 72)
    lines.append("공감 피크 구간 — 관객 다수가 강하게 반응한 시간대 우선 추출")
    lines.append(f"(공감 비율 기준: {pct_used}% 이상, 목표 {target_low}~{target_high}개 중 {len(peaks)}개 선정)")
    if relax_notes:
        lines.append("(기준 완화: " + " / ".join(relax_notes) + ")")
    lines.append("=" * 72)
    lines.append("")

    if not peaks:
        lines.append("탐지된 공감 피크 구간이 없습니다. 데이터/기준을 다시 확인해주세요.")
        return "\n".join(lines)

    for rank, p in enumerate(peaks, 1):
        matched_scenes = match_scenes(p, scenes)
        scene_ids = ", ".join(sc["scene"] for sc in matched_scenes) if matched_scenes else "해당 장면 없음"
        sentence_matches = find_sentence_matches(p, scenes)

        lines.append("-" * 72)
        lines.append(f"[{rank}순위] {sec_to_mmss(p['start'])} - {sec_to_mmss(p['end'])}  (소속 장면: {scene_ids})")
        lines.append(f"감정 : {p['emotion']}  ({p['agree_count']}/{p['total_faces']}명, {p['agree_pct']}%)")

        breakdown_str = ", ".join(
            f"{e} {c}명" for e, c in sorted(p["breakdown"].items(), key=lambda x: -x[1])
        )
        lines.append(f"전체 분포 : {breakdown_str}")
        if p["agree_pct"] < STRONG_PCT:
            lines.append(f"※ 약한 피크: 공감률 {STRONG_PCT:g}% 미만이지만 목표 개수를 채우기 위해 포함")

        lines.append("나레이션 (해당 구간과 겹치는 문장):")
        if sentence_matches:
            for sm in sentence_matches:
                lines.append(f"  [{sm['scene']}] {sec_to_mmss(sm['start_sec'])}-{sec_to_mmss(sm['end_sec'])}  \"{sm['text']}\"")
        else:
            lines.append("  (이 구간엔 겹치는 내레이션 문장 없음 — 사운드만 재생 중이었을 가능성)")

        lines.append("사운드 특성 :")
        for sc in matched_scenes:
            lines.append(f"  [{sc['scene']}] {sc['sound_label']} : {sc['sound_desc']}")

        lines.append("")

    lines.append("=" * 72)
    return "\n".join(lines)


def main(timetable_path, csv_path, output_path, window_size, step,
         min_gap, target_low, target_high, exclude_neutral, min_agree=2):
    scenes = parse_timetable(timetable_path)
    rows = load_emotion_rows(csv_path)

    duration = scenes[-1]["end_sec"] if scenes else (
        max((r["timestamp_sec"] for r in rows), default=0)
    )

    peaks, pct_used, relax_notes = find_peaks_targeting_count(
        rows, window_size, step, duration, exclude_neutral,
        min_gap, target_low, target_high,
        base_min_agree=min_agree,
    )

    output_text = format_output(peaks, scenes, pct_used, target_low, target_high, relax_notes)
    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write(output_text)

    print(f"최종 공감 비율 기준: {pct_used}% / 선정된 피크: {len(peaks)}개")
    if relax_notes:
        print("기준 완화: " + " / ".join(relax_notes))
    weak = sum(1 for p in peaks if p["agree_pct"] < STRONG_PCT)
    if weak:
        print(f"약한 피크(공감률 {STRONG_PCT:g}% 미만): {weak}개")
    if len(peaks) < target_low:
        print(f"[경고] 모든 기준을 완화해도 {len(peaks)}개뿐입니다 (중립 외 반응이 거의 없는 데이터일 수 있음)")
    print(f"완료. 저장됨: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timetable", required=True, help="타임테이블 txt 경로 (문장단위 타임스탬프 포맷)")
    parser.add_argument("--emotion_csv", required=True, help="감정 분석 csv 경로")
    parser.add_argument("--output", default="../output/emotion_peaks.txt")
    parser.add_argument("--window_size", type=float, default=10.0,
                        help="공감 여부를 판단할 시간창 길이(초)")
    parser.add_argument("--step", type=float, default=5.0,
                        help="시간창 이동 간격(초)")
    parser.add_argument("--min_gap", type=float, default=5.0,
                        help="선택된 피크 구간끼리 최소 몇 초는 떨어지게 할지")
    parser.add_argument("--target_low", type=int, default=4, help="목표 결과 개수 하한")
    parser.add_argument("--target_high", type=int, default=6, help="목표 결과 개수 상한")
    parser.add_argument("--min_agree", type=int, default=2,
                        help="최소 몇 명 이상 일치해야 피크로 인정할지 (혼자 테스트할 땐 1로 낮추세요)")
    parser.add_argument("--include_neutral", action="store_true",
                        help="'중립'도 감정 후보에 포함 (기본은 제외)")
    args = parser.parse_args()

    main(
        args.timetable, args.emotion_csv, args.output,
        args.window_size, args.step, args.min_gap,
        args.target_low, args.target_high,
        exclude_neutral=not args.include_neutral,
        min_agree=args.min_agree,
    )