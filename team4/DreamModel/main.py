"""Render a preview or the complete four-act DreamModel animation."""

from __future__ import annotations

import argparse
from dataclasses import replace
import io
from pathlib import Path
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from team4.DreamModel.config import REPO_ROOT, RenderConfig
from team4.DreamModel.runtime.dream_pipeline import render
from team4.DreamModel.runtime.audience import AudienceAtmosphere


def parse_config(argv: list[str] | None = None) -> tuple[RenderConfig, Path | None]:
    parser = argparse.ArgumentParser(description="DreamModel: Formation From an Empty State")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke", action="store_true", help="640x360, 30fps, 원본 시간 0–20초 생성 검수 (기본)")
    mode.add_argument("--preview", action="store_true", help="960x540, 30fps, 빈 상태부터 형성되는 원본 0–20초")
    mode.add_argument("--final", action="store_true", help="1920×1080, 30fps, 4×75초 완성본")
    parser.add_argument('--preview-start',type=float,default=0.,help='원본 300초 중 프리뷰 시작 시각')
    parser.add_argument('--preview-seconds',type=float,default=20.,help='프리뷰 길이; 재생 속도 변경 없음')
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--input-dir", type=Path, default=REPO_ROOT / "team4/input")
    parser.add_argument("--audio", type=Path, help="명시적 오디오 파일. 미지정 시 공통 입력에서 탐색")
    parser.add_argument("--output", type=Path, help="MP4 저장 경로")
    parser.add_argument("--report", type=Path, help="실행 보고서 JSON 저장 경로")
    parser.add_argument("--transition-seconds", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--semantic-config", type=Path, help="예술적 감정·스토리 규칙 설정 JSON")
    parser.add_argument('--audience-arousal',type=float,default=.5,help='관객 집단 활성도 0–1; 기본값은 관측 데이터가 아님')
    parser.add_argument('--audience-tension',type=float,default=.5,help='관객 집단 긴장도 0–1')
    parser.add_argument('--audience-coherence',type=float,default=.5,help='관객 집단 반응 일치도 0–1')
    parser.add_argument('--audience-source',default='preview defaults; no measured audience aggregate supplied')
    args = parser.parse_args(argv)
    if args.transition_seconds is not None:
        parser.error("Current DreamModel uses fixed transition growth at 65, 140 and 215 seconds; --transition-seconds is unsupported.")
    smoke = not args.final
    output_dir = REPO_ROOT / "team4/DreamModel/output"
    config = RenderConfig(output_path=output_dir/'collective_dream_final.mp4',
                          report_path=output_dir/'collective_dream_final_report.json')
    if smoke:
        config = replace(config, width=640, height=360, scene_seconds=75.0,scene_count=1,
                         transition_seconds=20.0,smoke=True,preview_start_seconds=args.preview_start,preview_seconds=args.preview_seconds,
                         output_path=output_dir / "collective_dream_smoke.mp4",
                         report_path=output_dir / "collective_dream_smoke_report.json")
    if args.preview:
        config = replace(config, width=960, height=540,
                         output_path=output_dir / "collective_dream_preview.mp4",
                         report_path=output_dir / "collective_dream_preview_report.json")
    changes = {"seed": args.seed, "input_root": args.input_dir.resolve()}
    changes['audience']=AudienceAtmosphere(args.audience_arousal,args.audience_tension,
        args.audience_coherence,args.audience_source)
    if args.output:
        changes["output_path"] = args.output.resolve()
        if not args.report:
            changes["report_path"] = args.output.resolve().with_name(args.output.stem + "_run_report.json")
    if args.report:
        changes["report_path"] = args.report.resolve()
    if args.transition_seconds is not None:
        changes["transition_seconds"] = args.transition_seconds
    if args.semantic_config:
        changes["semantic_config"] = args.semantic_config.resolve()
    return replace(config, **changes), args.audio.resolve() if args.audio else None


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    try:
        config, audio_path = parse_config(argv)
        if config.smoke:
            render(config, audio_path)
        else:
            from team4.DreamModel.runtime.render_final import render as render_final
            render_final(config, audio_path)
    except (ValueError, OSError, RuntimeError) as error:
        print(f"[오류] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
