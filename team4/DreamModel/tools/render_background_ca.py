# -*- coding: utf-8 -*-
"""
render_background_ca.py — 꿈 재현 배경 애니메이션(MemoryCA + Open-Ended Evolution) 생성 및 프리뷰 도구

[사용법] (저장소 루트 Capstone2 에서)
  1) 1·2·3번 표준 시나리오 5분(300초, 1920x1080, 30fps, 9,000프레임) 배경 영상 생성:
     python -m team4.DreamModel.tools.render_background_ca --film 1
     python -m team4.DreamModel.tools.render_background_ca --film 2
     python -m team4.DreamModel.tools.render_background_ca --film 3
     python -m team4.DreamModel.tools.render_background_ca --films 1,2,3

  2) 빠른 핵심 프레임(15장) 프리뷰 시트 생성:
     python -m team4.DreamModel.tools.render_background_ca --film 1 --preview

  3) 공통 입력 슬롯(team4/input/storyboard)에서 직접 렌더링:
     python -m team4.DreamModel.tools.render_background_ca --from-input --sound <음원경로>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team4.DreamModel.runtime import background_ca_engine as m
from team4.DreamModel.runtime.background_scene_decomposer import (
    SCENARIO_NAMES,
    DreamBackgroundRenderer,
)


INPUT_SLOT = REPO_ROOT / "team4" / "input"
ASSETS_SCENARIOS = REPO_ROOT / "team4" / "DreamModel" / "configs" / "scenarios"
DEFAULT_OUT = REPO_ROOT / "team4" / "DreamModel" / "output"


def make_plate_comparison_sheet(
    scenario_dir: Path,
    shots: list[tuple[float, np.ndarray]],
    out_path: Path,
    label_prefix: str,
):
    """원본 배경판(scene_01~04.png)과 셀룰러 오토마타 재현 프레임을 나란히 비교하는 시트 생성."""
    rows = []
    target_times = [24.0, 108.0, 195.0, 262.0]
    shot_map = {round(t): im for t, im in shots}
    for t in target_times:
        our_rgb = shot_map.get(round(t))
        if our_rgb is None:
            continue
        our_bgr = cv2.resize(our_rgb[..., ::-1].copy(), (640, 360), interpolation=cv2.INTER_AREA)
        sc_idx = min(3, int(t // 75.0))
        plate_path = scenario_dir / f"scene_{sc_idx + 1:02d}.png"
        plate_bgr = cv2.imdecode(np.fromfile(str(plate_path), np.uint8), cv2.IMREAD_COLOR)
        plate_bgr = cv2.resize(plate_bgr, (640, 360), interpolation=cv2.INTER_AREA)

        stamp = f"{int(t // 60)}:{int(t % 60):02d}"
        cv2.putText(plate_bgr, f"Source Plate scene_0{sc_idx+1} ({stamp})", (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (245, 245, 245), 2, cv2.LINE_AA)
        cv2.putText(our_bgr, f"CA+OpenEnded Background ({label_prefix} {stamp})", (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (245, 245, 245), 2, cv2.LINE_AA)
        rows.append(np.hstack([plate_bgr, our_bgr]))
    if rows:
        sheet = np.vstack(rows)
        ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if ok:
            buf.tofile(str(out_path))


def run_render(
    film: int = 1,
    scenario_dir: Path | None = None,
    sound_path: Path | None = None,
    out_dir: Path = DEFAULT_OUT,
    preview: bool = False,
):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(4)
    torch.set_num_threads(4)

    if scenario_dir is None:
        scenario_dir = ASSETS_SCENARIOS / SCENARIO_NAMES[film]
    if sound_path is None:
        sound_path = INPUT_SLOT / "background" / f"{film}번_꿈재현_배경_사운드.mp4"

    seed = 27 + film
    torch.manual_seed(seed)
    t0 = time.monotonic()

    with torch.inference_mode():
        R = DreamBackgroundRenderer(scenario_dir=scenario_dir, sound_path=sound_path, film=film, seed=seed)
        times = [6, 24, 49, 66, 87, 108, 131, 158, 180, 195, 214, 237, 262, 282, 296]
        wanted = {round(t * m.FPS) for t in times}
        shots = []

        if not preview:
            final_mp4 = out_dir / f"{film}번_꿈재현_배경_v3_사운드.mp4"
            cmd = [
                m.FFMPEG, "-y", "-v", "error",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{m.W}x{m.H}", "-r", str(m.FPS),
                "-i", "-", "-i", str(sound_path),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-threads", "6", "-preset", "fast",
                "-b:v", "17200k", "-minrate", "17200k", "-maxrate", "17200k", "-bufsize", "34400k",
                "-x264-params", "nal-hrd=cbr:force-cfr=1",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-t", "300", "-movflags", "+faststart", str(final_mp4),
            ]
            enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        last_log = time.monotonic()
        for f in range(m.N):
            show = (not preview) or any(0 <= w - f < 3 for w in wanted)
            im = R.frame(f, render=show)
            if show:
                im_u8 = m.to_u8(im)
            if not preview:
                enc.stdin.write(im_u8.tobytes())
            if f in wanted:
                shots.append((f / m.FPS, im_u8.copy()))
            if time.monotonic() - last_log >= 15.0:
                el = time.monotonic() - t0
                fps_cur = (f + 1) / max(el, 1e-3)
                eta = (m.N - f - 1) / max(fps_cur, 1e-3)
                print(
                    f"  [{film}번 {'PREVIEW' if preview else 'RENDER'}] {f+1}/{m.N} ({100*(f+1)/m.N:.1f}%) | "
                    f"{fps_cur:.1f} fps | 경과 {el/60:.1f}분 | 남은시간 {eta/60:.1f}분",
                    flush=True,
                )
                last_log = time.monotonic()

        sheet_path = out_dir / f"{film}번_장면흐름_v3.jpg"
        comp_path = out_dir / f"{film}번_원본대비_비교_v3.jpg"
        m.contact_sheet(shots, sheet_path, f"Scenario {film}")
        make_plate_comparison_sheet(scenario_dir, shots, comp_path, f"Scenario {film}")

        if preview:
            print(f"[PREVIEW 완료] {sheet_path} / {comp_path} ({time.monotonic() - t0:.1f}s)")
            return

        enc.stdin.close()
        code = enc.wait()
        assert code == 0, f"FFmpeg encode failed with code {code}"

        check = subprocess.run([m.FFMPEG, "-v", "error", "-threads", "4", "-i", str(final_mp4), "-f", "null", "-"], capture_output=True)
        assert check.returncode == 0 and not check.stderr, check.stderr.decode(errors="replace")
        sz = final_mp4.stat().st_size
        report = dict(
            version="v3_plate_ca_linked",
            film=film,
            scenario=scenario_dir.name,
            sound_source=str(sound_path.name),
            file=str(final_mp4),
            width=m.W,
            height=m.H,
            fps=m.FPS,
            frames=m.N,
            duration_seconds=m.DUR,
            bytes=sz,
            gigabytes_decimal=round(sz / 1e9, 4),
            memory_ca=R.stats(),
            field_evolution=R.evolution_report(),
            elapsed_minutes=round((time.monotonic() - t0) / 60.0, 2),
        )
        (out_dir / f"{film}번_제작검증_v3.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[완료] {final_mp4} ({sz:,} bytes / {sz/1e9:.3f} GB) | {report['elapsed_minutes']}분 소요", flush=True)


def main():
    ap = argparse.ArgumentParser(description="꿈 재현 배경 애니메이션 생성기 (Cellular Automata + Open-Ended Evolution)")
    ap.add_argument("--film", type=int, default=1, choices=[1, 2, 3], help="표준 시나리오 번호 (1, 2, 3)")
    ap.add_argument("--films", type=str, default="", help="쉼표로 구분된 시나리오 번호 목록 (예: 1,2,3)")
    ap.add_argument("--from-input", action="store_true", help="team4/input/storyboard 슬롯에서 입력 로드")
    ap.add_argument("--scenario-dir", type=str, default="", help="배경판 4장 및 scenes.json이 위치한 폴더 경로")
    ap.add_argument("--sound", type=str, default="", help="사운드 동기화 및 결합에 사용할 오디오/비디오 파일 경로")
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT), help="렌더링 결과 저장 폴더 (기본: team4/DreamModel/output)")
    ap.add_argument("--preview", action="store_true", help="전체 영상 대신 15개 핵심 시각 검증 시트(.jpg)만 고속 생성")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)

    if args.from_input:
        sc_dir = Path(args.scenario_dir) if args.scenario_dir else (INPUT_SLOT / "storyboard")
        snd = Path(args.sound) if args.sound else (INPUT_SLOT / "background" / f"{args.film}번_꿈재현_배경_사운드.mp4")
        run_render(film=args.film, scenario_dir=sc_dir, sound_path=snd, out_dir=out_dir, preview=args.preview)
        return

    if args.films:
        for f_id in [int(x.strip()) for x in args.films.split(",") if x.strip()]:
            run_render(film=f_id, out_dir=out_dir, preview=args.preview)
    else:
        sc_dir = Path(args.scenario_dir) if args.scenario_dir else None
        snd = Path(args.sound) if args.sound else None
        run_render(film=args.film, scenario_dir=sc_dir, sound_path=snd, out_dir=out_dir, preview=args.preview)


if __name__ == "__main__":
    main()
