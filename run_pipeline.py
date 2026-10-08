# -*- coding: utf-8 -*-
"""
run_pipeline.py — 1팀 감정 추출 → 2팀 꿈 이야기 생성까지 한 번에 실행

[흐름]
  1) team1/src/step3b_multi_camera_pipeline.py  관객 감정 → session_*.csv
  2) team1/src/step4_detect_peaks.py            감정 CSV + 타임테이블 → emotion_peaks.txt
  3) team1/src/step5_extract_keywords.py        emotion_peaks.txt → keyword_pool.json
     team1/src/step6_assemble_blueprint.py      keyword_pool.json → assembled_blueprint.json
  4) team2/step1_parse.py                       emotion_peaks.txt → parsed_scenes.json
  5) team2/step2_story_v2.py                    parsed_scenes.json → dream_scenes.json

step6의 설계도는 team2 step2가 장면1 재료로 쓴다. 설계도가 없으면 step2가
emotion_peaks에서 직접 재료를 뽑는 대안 경로로 동작한다.

각 스크립트는 수정하지 않고 그대로 호출합니다. 경로는 전부 절대 경로로 넘겨서
어느 폴더에서 실행하든 같은 결과가 나옵니다.

[사용법] (저장소 루트 Capstone2 에서)
  # 실제 세션: 카메라 0, 1번 + 내레이션 자동 재생
  python run_pipeline.py --sources 0 1 --narration team1/video/narration.mp3

  # 카메라 없이 기존 감정 CSV로 테스트 (step3b 건너뜀)
  python run_pipeline.py --emotion-csv team1/output/multi_test.csv

  # 피크까지만 / 파싱까지만 돌리기
  python run_pipeline.py --emotion-csv team1/output/multi_test.csv --until peaks
  python run_pipeline.py --emotion-csv team1/output/multi_test.csv --until parse
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEAM1 = ROOT / "team1"
TEAM1_SRC = TEAM1 / "src"
TEAM1_OUT = TEAM1 / "output"
TEAM2 = ROOT / "team2"
TEAM2_OUT = TEAM2 / "output"

STEP3B = TEAM1_SRC / "step3b_multi_camera_pipeline.py"
STEP4 = TEAM1_SRC / "step4_detect_peaks.py"
STEP5 = TEAM1_SRC / "step5_extract_keywords.py"
STEP6 = TEAM1_SRC / "step6_assemble_blueprint.py"
T2_STEP1 = TEAM2 / "step1_parse.py"
T2_STEP2 = TEAM2 / "step2_story_v2.py"

STAGES = ["capture", "peaks", "blueprint", "parse", "story"]


# ──────────────────────────────────────────────────────────
# 공통 유틸
# ──────────────────────────────────────────────────────────
def banner(title):
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64, flush=True)


def run(cmd, cwd, label):
    """하위 스크립트 실행. 실패하면 파이프라인 전체를 멈춘다."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"            # Windows에서 한글 입출력 깨짐 방지
    env["PYTHONIOENCODING"] = "utf-8"

    print("$ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd), flush=True)
    t0 = time.time()
    result = subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=env)
    elapsed = time.time() - t0

    if result.returncode != 0:
        sys.exit(f"\n[중단] {label} 단계에서 오류가 났습니다 (종료 코드 {result.returncode}).")
    print(f"[완료] {label} ({elapsed:.1f}초)", flush=True)


def require_file(path, what):
    if not Path(path).exists():
        sys.exit(f"[중단] {what} 파일이 없습니다: {path}")


def load_api_key():
    """2팀 step2가 쓰는 ANTHROPIC_API_KEY가 있는지 미리 확인 (.env도 확인)"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    for env_path in (ROOT / ".env", TEAM2 / ".env"):
        if env_path.exists():
            load_dotenv(env_path)
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def count_peaks(peaks_path):
    text = Path(peaks_path).read_text(encoding="utf-8-sig")
    return text.count("순위]")


# ──────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="1팀 감정 추출 → 2팀 꿈 이야기 통합 실행")

    # 입력
    src = ap.add_argument_group("입력 (둘 중 하나)")
    src.add_argument("--sources", nargs="+",
                     help="step3b 카메라 인덱스 또는 영상 경로 (예: --sources 0 1)")
    src.add_argument("--emotion-csv",
                     help="이미 만든 감정 CSV 경로. 주면 step3b(촬영)를 건너뜀")

    # step3b 옵션
    cap = ap.add_argument_group("step3b 감정 추출")
    cap.add_argument("--narration", help="촬영 시작 시 자동 재생할 내레이션 파일")
    cap.add_argument("--interval", type=float, default=0.5,
                     help="감정 분석 간격(초). step4 창 크기보다 작게 (기본 0.5)")
    cap.add_argument("--model", default="full", choices=["short", "full"])
    cap.add_argument("--device", default="auto", choices=["cpu", "gpu", "auto"])
    cap.add_argument("--no-batch", action="store_true")

    # step4 옵션
    pk = ap.add_argument_group("step4 피크 탐지")
    pk.add_argument("--timetable", default=str(TEAM1 / "timetable" / "sound_timetable.txt"))
    pk.add_argument("--window-size", type=float, default=2.0,
                    help="피크 창 크기(초). 기본 2초")
    pk.add_argument("--step", type=float, default=1.0,
                    help="창 이동 간격(초). 기본 1초")
    pk.add_argument("--min-gap", type=float, default=5.0)
    pk.add_argument("--target-low", type=int, default=4)
    pk.add_argument("--target-high", type=int, default=6)
    pk.add_argument("--min-agree", type=int, default=2,
                    help="혼자 테스트할 땐 1")
    pk.add_argument("--include-neutral", action="store_true")

    # step5·6 옵션
    bp = ap.add_argument_group("step5·6 설계도 진화")
    bp.add_argument("--iters", type=int, default=20000,
                    help="step6 진화 탐색 횟수 (기본 20000, 약 25초)")
    bp.add_argument("--bins", type=int, default=8, help="MAP-Elites 격자 한 변 칸 수")
    bp.add_argument("--seed", type=int, default=None,
                    help="고정하면 매번 같은 설계도, 비우면 매번 다른 꿈")
    bp.add_argument("--curiosity", type=float, default=0.3,
                    help="설계도 선택 시 기묘함 가중치 (높이면 더 기괴한 꿈)")

    # 실행 범위
    ap.add_argument("--until", choices=STAGES, default="story",
                    help="이 단계까지만 실행 (기본: story = 끝까지)")
    args = ap.parse_args()

    if not args.sources and not args.emotion_csv:
        ap.error("--sources 또는 --emotion-csv 중 하나는 꼭 필요합니다.")
    if args.sources and args.emotion_csv:
        ap.error("--sources와 --emotion-csv는 동시에 쓸 수 없습니다.")

    stop_at = STAGES.index(args.until)
    session = datetime.now().strftime("%Y%m%d_%H%M%S")

    TEAM1_OUT.mkdir(parents=True, exist_ok=True)
    TEAM2_OUT.mkdir(parents=True, exist_ok=True)

    # ── 사전 점검: 촬영 끝난 뒤에 터지지 않도록 미리 확인 ─────────
    require_file(args.timetable, "타임테이블")
    if args.narration:
        require_file(args.narration, "내레이션")
    if args.emotion_csv:
        require_file(args.emotion_csv, "감정 CSV")
    # step5도 키워드 뱅크에 없는 장면은 LLM으로 뽑으므로 키가 필요하다
    if stop_at >= STAGES.index("blueprint") and not load_api_key():
        sys.exit("[중단] ANTHROPIC_API_KEY가 없습니다. 환경변수나 Capstone2/.env 또는 team2/.env에 넣어주세요.\n"
                 "       (LLM 단계 없이 돌리려면 --until peaks)")

    emotion_csv = Path(args.emotion_csv).resolve() if args.emotion_csv \
        else TEAM1_OUT / f"session_{session}.csv"
    peaks_txt = TEAM1_OUT / "emotion_peaks.txt"
    keyword_pool = TEAM1_OUT / "keyword_pool.json"
    blueprint_json = TEAM1_OUT / "assembled_blueprint.json"
    parsed_json = TEAM2_OUT / "parsed_scenes.json"

    # ── 1) step3b: 감정 추출 ─────────────────────────────────────
    if args.sources:
        banner("1/5  [1팀 step3b] 관객 감정 추출  (q 누르면 종료)")
        cmd = [sys.executable, STEP3B,
               "--sources", *args.sources,
               "--output", emotion_csv,
               "--interval", args.interval,
               "--model", args.model,
               "--device", args.device]
        if args.narration:
            cmd += ["--narration", Path(args.narration).resolve()]
        if args.no_batch:
            cmd.append("--no-batch")
        run(cmd, TEAM1_SRC, "step3b")
        require_file(emotion_csv, "step3b 결과 CSV")
    else:
        banner("1/5  [1팀 step3b] 건너뜀 — 기존 CSV 사용")
        print(f"감정 CSV: {emotion_csv}")

    if stop_at == STAGES.index("capture"):
        print(f"\n--until capture → 여기서 종료. 결과: {emotion_csv}")
        return

    # ── 2) step4: 공감 피크 ──────────────────────────────────────
    banner("2/5  [1팀 step4] 공감 피크 탐지")
    cmd = [sys.executable, STEP4,
           "--timetable", Path(args.timetable).resolve(),
           "--emotion_csv", emotion_csv,
           "--output", peaks_txt,
           "--window_size", args.window_size,
           "--step", args.step,
           "--min_gap", args.min_gap,
           "--target_low", args.target_low,
           "--target_high", args.target_high,
           "--min_agree", args.min_agree]
    if args.include_neutral:
        cmd.append("--include_neutral")
    run(cmd, TEAM1_SRC, "step4")

    n_peaks = count_peaks(peaks_txt)
    if n_peaks == 0:
        sys.exit("[중단] 공감 피크가 하나도 없습니다. 인원이 적으면 --min-agree 1로 다시 시도해보세요.")
    # 세션별 기록도 남겨둠 (emotion_peaks.txt는 다음 실행 때 덮어써지므로)
    (TEAM1_OUT / f"emotion_peaks_{session}.txt").write_text(
        peaks_txt.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    print(f"피크 {n_peaks}개 → {peaks_txt}")

    if stop_at == STAGES.index("peaks"):
        print("\n--until peaks → 여기서 종료.")
        return

    # ── 3) 1팀 step5·6: 키워드 풀 → 설계도 진화 ──────────────────
    banner("3/5  [1팀 step5·6] 키워드 풀 + 설계도 진화")
    run([sys.executable, STEP5,
         "--peaks", peaks_txt,
         "--timetable", Path(args.timetable).resolve(),
         "--bank", TEAM1_OUT / "keyword_bank.json",
         "--output", keyword_pool], TEAM1_SRC, "step5")
    require_file(keyword_pool, "step5 결과 키워드 풀")

    cmd = [sys.executable, STEP6,
           "--pool", keyword_pool,
           "--out-dir", TEAM1_OUT,
           "--iters", args.iters,
           "--bins", args.bins,
           "--curiosity", args.curiosity]
    if args.seed is not None:
        cmd += ["--seed", args.seed]
    run(cmd, TEAM1_SRC, "step6")
    require_file(blueprint_json, "step6 결과 설계도")
    print(f"설계도 → {blueprint_json}")

    if stop_at == STAGES.index("blueprint"):
        print(f"\n--until blueprint → 여기서 종료. 결과: {blueprint_json}")
        return

    # ── 4) 2팀 step1: 피크 파싱 ──────────────────────────────────
    banner("4/5  [2팀 step1] 피크 → parsed_scenes.json")
    run([sys.executable, T2_STEP1, peaks_txt, TEAM2_OUT], ROOT, "team2 step1")

    if stop_at == STAGES.index("parse"):
        print(f"\n--until parse → 여기서 종료. 결과: {parsed_json}")
        return

    # ── 5) 2팀 step2: 꿈 이야기 ──────────────────────────────────
    banner("5/5  [2팀 step2] 꿈 이야기 4장면 생성")
    run([sys.executable, T2_STEP2, parsed_json, TEAM2_OUT], ROOT, "team2 step2")

    banner("전체 완료")
    print(f"  감정 CSV     : {emotion_csv}")
    print(f"  공감 피크    : {peaks_txt}")
    print(f"  설계도       : {blueprint_json}")
    print(f"  파싱 결과    : {parsed_json}")
    print(f"  꿈 이야기    : {TEAM2_OUT / 'dream_scenes.json'}")


if __name__ == "__main__":
    main()