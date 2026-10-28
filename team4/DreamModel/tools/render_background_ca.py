# -*- coding: utf-8 -*-
"""
render_background_ca.py — 꿈 재현 배경 애니메이션(StructuralDreamCA + PointGenesisGA) 생성 및 검증 도구

[사용법] (저장소 루트 Capstone2 에서)
  1) 표준 시나리오 5분(300초, 1920x1080, 30fps, 9,000프레임) 배경 영상 생성:
     python -m team4.DreamModel.tools.render_background_ca --film 1
     python -m team4.DreamModel.tools.render_background_ca --films 1,2,3

  2) 단계별 기법 분리 검증 (75초 한 장면의 상태를 갱신하고 시트만 저장):
     python -m team4.DreamModel.tools.render_background_ca --scenario-dir <경로> --mode ca_only --single-scene 1 --scene-sec 75 --preview --out-dir <출력폴더> --tag ca_only_preview
     python -m team4.DreamModel.tools.render_background_ca --scenario-dir <경로> --mode ga_only --single-scene 1 --scene-sec 75 --preview --out-dir <출력폴더> --tag ga_only_preview

  3) 최신 N1 스토리 ZIP과 사용자가 제공한 네 장면 영상으로 300초 생성:
     python -m team4.DreamModel.tools.render_background_ca --reference-video <dream.mp4> --story-zip <story.zip> --scene-sec 75 --out-dir <출력폴더> --tag n1_dream_300s

  4) 공통 입력 슬롯(team4/input/storyboard 또는 team4/main.py 연동)에서 직접 렌더링:
     python -m team4.DreamModel.tools.render_background_ca --from-input --scenario-dir <경로> --sound <음원경로> --out-dir <출력폴더>
"""
from __future__ import annotations

import argparse
import functools
import inspect
import json
import subprocess
import sys
import time
import uuid
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
    compute_cycle_params,
)


INPUT_SLOT = REPO_ROOT / "team4" / "input"
ASSETS_SCENARIOS = REPO_ROOT / "team4" / "DreamModel" / "configs" / "scenarios"
DEFAULT_OUT = REPO_ROOT / "team4" / "DreamModel" / "output"


def _locked_render(fn):
    """Reject concurrent writers to one deliverable; crash releases the OS lock."""
    @functools.wraps(fn)
    def guarded(*args, **kwargs):
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        output = Path(bound.arguments['out_dir'])
        output.mkdir(parents=True, exist_ok=True)
        name = bound.arguments['tag'] or f"film_{bound.arguments['film']}"
        with (output / f"{name}.render.lock").open('a+b') as lock:
            if lock.seek(0, 2) == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(f"Another render is writing {name}; keep that render running.") from exc
            return fn(*args, **kwargs)
    return guarded


def resolve_sound_path(sound_path: Path | None, film: int) -> Path:
    """지정된 사운드 경로가 없거나 누락된 경우 team4/input/sound 음원으로 자동 폴백."""
    if sound_path is not None and Path(sound_path).exists():
        return Path(sound_path)
    legacy_bg = INPUT_SLOT / "background" / f"{film}번_꿈재현_배경_사운드.mp4"
    if legacy_bg.exists():
        return legacy_bg
    snd_dir = INPUT_SLOT / "sound"
    if snd_dir.exists():
        tracks = sorted(
            p for p in snd_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".mp4"}
        )
        if tracks:
            return tracks[0]
    if sound_path is not None:
        return Path(sound_path)
    return legacy_bg


def build_sample_times(scene_sec: float, single_scene: int | None, scene_count: int = 4) -> list[float]:
    """
    반복 진화 사이클(1개 점 -> 목표 이미지 생성 -> 100% 완성 -> 파쇄 붕괴 -> 새 점에서 반복 재생성) 검증 타임스탬프 생성.
    """
    n_cycles, cycle_dur = compute_cycle_params(scene_sec)
    acts = 1 if single_scene is not None else scene_count
    return [round(act*scene_sec + cycle*cycle_dur + u*cycle_dur,3)
            for act in range(acts) for cycle in range(n_cycles)
            for u in (.012,.08,.18,.32,.50,.68,.79,.845,.88,.93,.97,.999)]



def make_progression_sheet(
    shots: list[tuple[float, np.ndarray]],
    out_path: Path,
    title: str,
    cols: int = 6,
    metadata: dict | None = None,
):
    """시간 순서에 따른 점 생성 -> 스케치/지우기 -> 선명 구조 형성 -> 불규칙 붕괴 -> 재진화 시트 저장."""
    if not shots:
        return
    tw, th = 480, 270
    n = len(shots)
    rows_cnt = (n + cols - 1) // cols
    canvas = np.full((rows_cnt * th + 46, cols * tw, 3), 16, np.uint8)
    cv2.putText(
        canvas,
        title,
        (16, 31),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.78,
        (240, 240, 240),
        2,
        cv2.LINE_AA,
    )
    for idx, (t, rgb) in enumerate(shots):
        r, c = divmod(idx, cols)
        y0 = 46 + r * th
        x0 = c * tw
        tile = cv2.resize(rgb[..., ::-1].copy(), (tw, th), interpolation=cv2.INTER_AREA)
        snap = (metadata or {}).get(round(t*30), {})
        stamp = f"{t:05.1f}s {snap.get('method','')} {snap.get('stage','')}"
        cv2.rectangle(tile, (6, 6), (474, 34), (12, 12, 12), -1)
        cv2.putText(tile, stamp, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (250, 244, 220), 1, cv2.LINE_AA)
        canvas[y0:y0 + th, x0:x0 + tw] = tile

    ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 93])
    if ok:
        buf.tofile(str(out_path))


def make_plate_comparison_sheet(
    scenario_dir: Path,
    shots: list[tuple[float, np.ndarray]],
    out_path: Path,
    label_prefix: str,
    scene_sec: float = 75.0,
    single_scene: int | None = None,
    scene_count: int = 4,
):
    """원본 배경판(scene_01~04.png)과 형성기 프레임을 나란히 비교하는 시트 생성."""
    if not shots:
        return
    rows = []
    n_cycles, _ = compute_cycle_params(scene_sec)
    peak_fr = 0.845 / n_cycles
    if single_scene is not None:
        target_pairs = [(single_scene, scene_sec * peak_fr)]
    else:
        target_pairs = [(sc_idx, (sc_idx + peak_fr) * scene_sec) for sc_idx in range(scene_count)]

    for sc_idx, target_t in target_pairs:
        best_t, our_rgb = min(shots, key=lambda item: abs(item[0] - target_t))
        our_bgr = cv2.resize(our_rgb[..., ::-1].copy(), (640, 360), interpolation=cv2.INTER_AREA)
        plate_path = scenario_dir / f"scene_{sc_idx + 1:02d}.png"
        plate_bgr = cv2.imdecode(np.fromfile(str(plate_path), np.uint8), cv2.IMREAD_COLOR)
        plate_bgr = cv2.resize(plate_bgr, (640, 360), interpolation=cv2.INTER_AREA)

        stamp = f"{int(best_t // 60)}:{int(best_t % 60):02d}"
        cv2.rectangle(plate_bgr, (8, 8), (450, 40), (15, 15, 15), -1)
        cv2.rectangle(our_bgr, (8, 8), (560, 40), (15, 15, 15), -1)
        cv2.putText(
            plate_bgr,
            f"Source Plate scene_0{sc_idx+1} ({stamp})",
            (14, 31),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (245, 245, 245),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            our_bgr,
            f"DreamModel {label_prefix} ({stamp})",
            (14, 31),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (245, 245, 245),
            2,
            cv2.LINE_AA,
        )
        rows.append(np.hstack([plate_bgr, our_bgr]))

    if rows:
        sheet = np.vstack(rows)
        ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 93])
        if ok:
            buf.tofile(str(out_path))


def prepare_reference_inputs(video_path: Path, story_zip: Path, out_dir: Path) -> Path:
    """Extract four ordered reference frames and the current Team3 storyline.

    Only explicitly named archive entries are read; no archive instructions are
    executed and no Team1/2/3 or object files are overwritten.
    """
    import zipfile
    import hashlib
    reference_dir = out_dir / "reference_inputs"
    reference_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(story_zip) as archive:
        matches = [n for n in archive.namelist() if n.endswith("/team3/background/input/storyboard/dream_scenes.json")]
        if len(matches) != 1:
            raise ValueError("Expected exactly one current Team3 storyboard in the archive")
        story_data = archive.read(matches[0])
        parsed = json.loads(story_data.decode("utf-8-sig"))
        if len(parsed["scenes"]) != 4:
            raise ValueError("Expected four ordered story scenes")
        (reference_dir / "dream_scenes.json").write_bytes(story_data)
        story_member = matches[0]
    cap = cv2.VideoCapture(str(video_path))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if frame_count < 4 or fps <= 0:
        raise ValueError("Unreadable reference video")
    reference_frames = []
    for act in range(4):
        index = int((act + 0.5) * frame_count / 4)
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok: raise RuntimeError(f"Cannot read reference frame {index}")
        path = reference_dir / f"scene_{act+1:02d}.png"
        cv2.imencode(".png", frame)[1].tofile(str(path))
        reference_frames.append(dict(scene=act+1,frame=index,seconds=index/fps))
    cap.release()
    provenance = dict(video=str(video_path),story_zip=str(story_zip),story_member=story_member,
        frames=reference_frames,story_sha256=hashlib.sha256(story_data).hexdigest(),
        emotions=[s["main_emotion"]["label"] for s in parsed["scenes"]])
    (reference_dir/"provenance.json").write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding="utf-8")
    return reference_dir


def prepare_reference_audio(story_zip: Path, out_dir: Path) -> Path:
    """Use only the background soundtrack supplied in the user's archive."""
    import zipfile
    import hashlib
    with zipfile.ZipFile(story_zip) as archive:
        names=[n for n in archive.namelist() if n.endswith('/team4/input/sound/dream_sound.wav')]
        if len(names)!=1:
            raise ValueError('Expected one supplied background soundtrack; pass --sound explicitly')
        data=archive.read(names[0])
    path=out_dir/'reference_inputs'/'dream_sound.wav'
    path.write_bytes(data)
    (path.parent/'audio_provenance.json').write_text(json.dumps(dict(
        archive=str(story_zip),member=names[0],sha256=hashlib.sha256(data).hexdigest(),
        added_narration=False,source_timing_preserved=True),ensure_ascii=False,indent=2),encoding='utf-8')
    return path


@_locked_render
def run_render(
    film: int = 1,
    scenario_dir: Path | None = None,
    sound_path: Path | None = None,
    out_dir: Path = DEFAULT_OUT,
    preview: bool = False,
    mode: str = "hybrid",
    scene_sec: float = 75.0,
    single_scene: int | None = None,
    tag: str = "",
    reference_video: Path | None = None,
    story_zip: Path | None = None,
    scene_count: int = 4,
):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(4)
    torch.set_num_threads(4)

    if reference_video is not None:
        if story_zip is None: raise ValueError("--reference-video requires --story-zip")
        scenario_dir = prepare_reference_inputs(Path(reference_video), Path(story_zip), out_dir)
        sound_path = Path(sound_path) if sound_path is not None else prepare_reference_audio(Path(story_zip),out_dir)
    else:
        if scenario_dir is None: scenario_dir = ASSETS_SCENARIOS / SCENARIO_NAMES[film]
        sound_path = resolve_sound_path(sound_path, film)

    seed = 27 + film
    torch.manual_seed(seed)
    t0 = time.monotonic()

    with torch.inference_mode():
        R = DreamBackgroundRenderer(
            scenario_dir=scenario_dir,
            sound_path=sound_path,
            film=film,
            seed=seed,
            mode=mode,
            scene_sec=scene_sec,
            single_scene=single_scene,
            scene_count=scene_count,
        )
        total_frames = R.total_frames
        total_dur = R.total_dur

        sample_times = build_sample_times(scene_sec, single_scene, scene_count)
        wanted = {min(total_frames - 1, max(0, int(round(t * m.FPS)))) for t in sample_times}
        shots: list[tuple[float, np.ndarray]] = []
        metadata = {}

        if tag:
            final_mp4 = out_dir / f"{tag}.mp4"
            sheet_path = out_dir / f"{tag}_progression.jpg"
            comp_path = out_dir / f"{tag}_comparison.jpg"
            report_path = out_dir / f"{tag}_report.json"
        else:
            final_mp4 = out_dir / f"{film}번_꿈재현_배경_v3_사운드.mp4"
            sheet_path = out_dir / f"{film}번_장면흐름_v3.jpg"
            comp_path = out_dir / f"{film}번_원본대비_비교_v3.jpg"
            report_path = out_dir / f"{film}번_제작검증_v3.json"

        enc = None
        if not preview:
            # An incomplete or failed encode must never become the deliverable.
            encode_mp4 = final_mp4.with_name(f"{final_mp4.stem}.part-{uuid.uuid4().hex}.mp4")
            cmd = [
                m.FFMPEG, "-y", "-v", "error",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{m.W}x{m.H}", "-r", str(m.FPS),
                "-i", "-",
                *([*( ["-ss",str(single_scene*scene_sec)] if single_scene is not None else []),
                   "-i", str(sound_path), "-map", "0:v:0", "-map", "1:a:0"] if sound_path is not None else ["-an"]),
                "-c:v", "libx264", "-threads", "6", "-preset", "fast",
                "-b:v", "17200k", "-minrate", "17200k", "-maxrate", "17200k", "-bufsize", "34400k",
                "-x264-params", "nal-hrd=cbr:force-cfr=1",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{total_dur:.2f}", "-shortest", "-movflags", "+faststart", str(encode_mp4),
            ]
            enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        last_log = time.monotonic()
        for f in range(total_frames):
            show = (not preview) or (f in wanted)
            im = R.frame(f, render=show)
            if show and im is not None:
                im_u8 = m.to_u8(im)
                if not preview and enc is not None and enc.stdin is not None:
                    enc.stdin.write(im_u8.tobytes())
                if f in wanted:
                    shots.append((f / m.FPS, im_u8.copy()))
                    metadata[f] = R.last_snapshot.copy()
            if time.monotonic() - last_log >= 10.0:
                el = time.monotonic() - t0
                fps_cur = (f + 1) / max(el, 1e-3)
                eta = (total_frames - f - 1) / max(fps_cur, 1e-3)
                print(
                    f"  [{tag or f'{film}번'} {mode.upper()} {'PREVIEW' if preview else 'RENDER'}] "
                    f"{f+1}/{total_frames} ({100*(f+1)/total_frames:.1f}%) | "
                    f"{fps_cur:.1f} fps | 경과 {el:.1f}s | 남은시간 {eta:.1f}s",
                    flush=True,
                )
                last_log = time.monotonic()

        validation = R.validate()
        label = f"{scenario_dir.name} | mode={mode}" + (f" | scene={single_scene+1}" if single_scene is not None else "")
        make_progression_sheet(shots, sheet_path, label, cols=5, metadata=metadata)
        make_plate_comparison_sheet(
            scenario_dir,
            shots,
            comp_path,
            f"{mode.upper()}",
            scene_sec=scene_sec,
            single_scene=single_scene,
            scene_count=scene_count,
        )

        if preview:
            report_path.write_text(json.dumps(dict(validation=validation,cycles=R.cycle_records),ensure_ascii=False,indent=2),encoding="utf-8")
            print(f"[PREVIEW 완료] {sheet_path} / {comp_path} ({time.monotonic() - t0:.1f}s)", flush=True)
            return

        assert enc is not None and enc.stdin is not None
        enc.stdin.close()
        code = enc.wait()
        assert code == 0, f"FFmpeg encode failed with code {code}"

        check = subprocess.run(
            [m.FFMPEG, "-v", "error", "-threads", "4", "-i", str(encode_mp4), "-f", "null", "-"],
            capture_output=True,
        )
        if check.returncode != 0 or check.stderr:
            error_log = final_mp4.with_name(final_mp4.stem + "_decode_error.log")
            error_log.write_bytes(check.stderr)
            raise RuntimeError(f"Encoded video failed verification; details saved to {error_log}: "
                               + check.stderr[:600].decode(errors="replace"))
        encode_mp4.replace(final_mp4)
        sz = final_mp4.stat().st_size
        report = dict(
            version="v12_restored_v10_motion_continuous_audio",
            validation=validation,
            cycles=R.cycle_records,
            sampled_frames=metadata,
            mode=mode,
            scene_count=R.scene_count,
            film=film,
            scenario=scenario_dir.name,
            single_scene=(single_scene + 1) if single_scene is not None else None,
            sound_source=str(sound_path.name) if sound_path is not None else None,
            file=str(final_mp4),
            progression_sheet=str(sheet_path),
            comparison_sheet=str(comp_path),
            width=m.W,
            height=m.H,
            fps=m.FPS,
            frames=total_frames,
            duration_seconds=total_dur,
            bytes=sz,
            gigabytes_decimal=round(sz / 1e9, 4),
            scene_profiles=[
                {
                    "scene": i + 1,
                    "emotion": p["emotion_ko"],
                    "intensity": p["intensity"],
                    "emotion_vector": p["emotion_vector"],
                    "background_story_timing": p["background_story_timing"],
                    "mood_style": p.get("mood_style", ""),
                    "canvas_key": p["canvas_key"],
                    "arch_mode": p["arch_mode"],
                    "ga_lead": round(p["ga_lead"], 3),
                    "ca_lead": round(p["ca_lead"], 3),
                    "loco_vel": round(p["loco_vel"], 3),
                    "aperture_amp": round(p["aperture_amp"], 3),
                    "wave_amp": round(p["wave_amp"], 3),
                }
                for i, p in enumerate(R.profiles)
            ],
            memory_ca=R.stats(),
            field_evolution=R.evolution_report(),
            elapsed_seconds=round(time.monotonic() - t0, 2),
            elapsed_minutes=round((time.monotonic() - t0) / 60.0, 2),
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[완료] {final_mp4} ({sz:,} bytes / {sz/1e6:.1f} MB) | {report['elapsed_seconds']}s 소요\n"
            f"       시계열 시트: {sheet_path}",
            flush=True,
        )


def main():
    ap = argparse.ArgumentParser(description="꿈 재현 배경 애니메이션 생성기 (StructuralDreamCA + PointGenesisGA)")
    ap.add_argument("--film", type=int, default=1, choices=[1, 2, 3], help="표준 시나리오 번호 (1, 2, 3)")
    ap.add_argument("--films", type=str, default="", help="쉼표로 구분된 시나리오 번호 목록 (예: 1,2,3)")
    ap.add_argument("--from-input", action="store_true", help="team4/input/storyboard 슬롯에서 입력 로드")
    ap.add_argument("--scenario-dir", type=str, default="", help="배경판 4장 및 메타데이터가 위치한 폴더 경로")
    ap.add_argument("--sound", type=str, default="", help="사운드 동기화 및 결합에 사용할 오디오/비디오 파일 경로")
    ap.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT), help="렌더링 결과 저장 폴더")
    ap.add_argument("--preview", action="store_true", help="전체 영상 인코딩 대신 시계열 시각 검증 시트(.jpg)만 고속 생성")
    ap.add_argument("--mode", type=str, default="hybrid", choices=["hybrid", "ca_only", "ga_only"], help="기법 실행 모드")
    ap.add_argument("--scene-sec", type=float, default=75.0, help="장면당 길이(초). 기본 75초(총 300초)")
    ap.add_argument("--single-scene", type=int, default=0, choices=[0, 1, 2, 3, 4], help="단일 장면 집중 검증 번호 (1~4, 0이면 4막 전체)")
    ap.add_argument("--scene-count", type=int, default=4, choices=[1,2,3,4], help="Render the first N acts without changing their order")
    ap.add_argument("--tag", type=str, default="", help="별도 검증 출력 파일 접두어 (미지정 시 기본 파일명 유지)")
    ap.add_argument("--reference-video", type=Path, help="Four ordered goal scenes in the supplied video")
    ap.add_argument("--story-zip", type=Path, help="Archive containing the current Team3 storyboard")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    single_idx = (args.single_scene - 1) if args.single_scene in (1, 2, 3, 4) else None

    if args.from_input:
        sc_dir = Path(args.scenario_dir) if args.scenario_dir else (INPUT_SLOT / "storyboard")
        snd = Path(args.sound) if args.sound else None
        run_render(
            film=args.film,
            scenario_dir=sc_dir,
            sound_path=snd,
            out_dir=out_dir,
            preview=args.preview,
            mode=args.mode,
            scene_sec=args.scene_sec,
            single_scene=single_idx,
            tag=args.tag,
            reference_video=args.reference_video,
            story_zip=args.story_zip,
            scene_count=args.scene_count,
        )
        return

    if args.films:
        for f_id in [int(x.strip()) for x in args.films.split(",") if x.strip()]:
            run_render(
                film=f_id,
                out_dir=out_dir,
                preview=args.preview,
                mode=args.mode,
                scene_sec=args.scene_sec,
                single_scene=single_idx,
                tag=f"{args.tag}_film{f_id}" if args.tag else "",
                reference_video=args.reference_video,
                story_zip=args.story_zip,
                scene_count=args.scene_count,
            )
    else:
        sc_dir = Path(args.scenario_dir) if args.scenario_dir else None
        snd = Path(args.sound) if args.sound else None
        run_render(
            film=args.film,
            scenario_dir=sc_dir,
            sound_path=snd,
            out_dir=out_dir,
            preview=args.preview,
            mode=args.mode,
            scene_sec=args.scene_sec,
            single_scene=single_idx,
            tag=args.tag,
            reference_video=args.reference_video,
            story_zip=args.story_zip,
            scene_count=args.scene_count,
        )


if __name__ == "__main__":
    main()
