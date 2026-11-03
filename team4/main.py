"""Render v13 background and GridModel, then composite on one 300-second clock."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid


TEAM4_DIR = Path(__file__).resolve().parent
if str(TEAM4_DIR.parent) not in sys.path:
    sys.path.insert(0, str(TEAM4_DIR.parent))
from team4.video_encoding import DELIVERY_ENCODER, delivery_video_args

OUTPUT_DIR = TEAM4_DIR / "output"
SOUND_DIR = TEAM4_DIR / "input" / "sound"
BACKGROUND_DIR = TEAM4_DIR / "input" / "background"
GRID_SCRIPT = TEAM4_DIR / "Grid_Model" / "GridModel" / "pythonimagemodel.py"
MODEL_PYTHON = TEAM4_DIR / "DreamModel" / ".venv" / "Scripts" / "python.exe"
PYTHON_EXE = MODEL_PYTHON if MODEL_PYTHON.exists() else Path(sys.executable)
DURATION = 300
FPS = 30
SIZE = (1920, 1080)
SUPPORTED_EMOTIONS = {"기쁨", "슬픔", "분노", "공포", "놀람", "혐오", "중립"}


def find_music() -> Path:
    supported = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
    tracks = sorted(p for p in SOUND_DIR.iterdir()
                    if p.is_file() and p.suffix.lower() in supported)
    if len(tracks) != 1:
        raise RuntimeError(f"input/sound에는 음악 파일 하나만 두어 주세요: {tracks}")
    return tracks[0]


def find_background_video() -> Path:
    supported = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    videos = sorted(p for p in BACKGROUND_DIR.iterdir()
                    if p.is_file() and p.suffix.lower() in supported)
    if len(videos) != 1:
        raise RuntimeError(f"input/background에는 배경 영상 하나만 두어 주세요: {videos}")
    return videos[0]


def find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    result = subprocess.run(
        [str(PYTHON_EXE), "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def run(command: list[str], *, cwd: Path = TEAM4_DIR) -> None:
    print("[main] 실행:", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def check_model_environment() -> None:
    result = subprocess.run(
        [str(PYTHON_EXE), "-c", "import torch, cv2, numpy"],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(f"모델 Python 환경을 확인해 주세요: {PYTHON_EXE}\n{result.stderr[-1000:]}")


def validate_metadata() -> None:
    for name in ("scenes.json", "dream_scenes.json"):
        data = json.loads((BACKGROUND_DIR / name).read_text(encoding="utf-8-sig"))
        if name == "scenes.json":
            scenes = data.get("scenes", [])
            if len(scenes) != 4 or any(
                not isinstance(s, dict) or s.get("emotion") not in SUPPORTED_EMOTIONS
                for s in scenes
            ):
                raise ValueError("scenes.json에는 유효한 감정 라벨이 있는 네 장면이 필요합니다.")


def inspect_video(path: Path, *, rendered_layer: bool = True) -> dict:
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"영상을 읽을 수 없습니다: {path}")
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        duration = frames / fps if fps else 0
        if abs(duration - DURATION) > 0.10:
            raise ValueError(f"영상은 300초여야 합니다 (자동 반복/늘이기 없음): {path}, {duration:.3f}s")
        if rendered_layer and (size != SIZE or abs(fps - FPS) > 0.01 or frames != FPS * DURATION):
            raise ValueError(f"레이어 규격은 1920×1080, 30fps, 9000프레임입니다: {path}, {size}, {fps}, {frames}")
        return dict(width=size[0], height=size[1], fps=fps, frames=frames, duration_seconds=duration)
    finally:
        cap.release()


def background_command(source: Path) -> list[str]:
    # Use the v13 full-video path, including midpoint goals and temporal guidance.
    return [
        str(PYTHON_EXE), "-m", "team4.DreamModel.tools.render_background_ca",
        "--background-video", str(source), "--scenario-dir", str(BACKGROUND_DIR),
        "--silent", "--film", "1", "--scene-sec", "75", "--scene-count", "4",
        "--out-dir", str(OUTPUT_DIR), "--tag", "dreammodel_background_v13",
    ]


def opening_filter() -> str:
    """Reveal this run's composite from one living point, then pass through."""
    width, height = SIZE
    spot = max(8, 2 * round(height / 90))

    def ease(value: str) -> str:
        p = f'clip({value},0,1)'
        return f'({p}*{p}*(3-2*{p}))'

    growth = ease('(T-5)/9')
    join = ease('(T-14)/4')
    distance = 'hypot((X/W-0.5)*W/H,Y/H-0.5)'
    spread = f'clip((0.006+1.15*pow({growth},1.6)-{distance})/0.035,0,1)'
    mask = f'255*(0.85*{growth}*{spread}*(1-{join})+{join})'
    point = (f'255*{ease("(T-0.8)/1.2")}*(1-{ease("(T-5)/6")})'
             '*(0.85+0.1*sin(T*0.9)+0.05*sin(T*2.3))'
             '*exp(-(pow(X-W/2,2)+pow(Y-H/2,2))/(2*pow(W*0.13,2)))')
    # Only the first 540 frames are processed. The tail keeps its original
    # pixels and timing; the soundtrack stays on the existing audio branch.
    return (
        '[composed]split[head][tail];'
        '[head]trim=end_frame=540,setpts=PTS-STARTPTS[scene];'
        '[tail]trim=start_frame=540,setpts=PTS-STARTPTS[rest];'
        f'color=c=black:s={width}x{height}:r=30:d=18[dark];'
        f'color=c=0xffb8f4:s={spot}x{spot}:r=30:d=18,format=yuva420p,'
        f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='{point}'[point];"
        '[dark][point]overlay='
        "x='(W-w)/2+2*sin(t*0.83)+sin(t*1.73)':"
        "y='(H-h)/2+2*sin(t*1.13)':shortest=1:format=yuv420[seed];"
        'color=c=white:s=480x270:r=30:d=18,format=yuv420p,'
        f"geq=lum='{mask}':cb='{mask}':cr='{mask}',"
        f'scale={width}:{height}:flags=bilinear[reveal];'
        '[seed][scene][reveal]maskedmerge[opening];'
        '[opening][rest]concat=n=2:v=1:a=0[video]'
    )


def composition_filter() -> str:
    # Only the object's black canvas is removed. Background pixels are not
    # resized, blurred, graded, or blended with the Team3 source video.
    # The source's antialiased edge colors include the black canvas. Recover
    # straight RGB after a gradual key so those edges do not become dark halos.
    return (
        "[0:v]setpts=PTS-STARTPTS[bg];"
        "[1:v]fps=30,setpts=N/(30*TB),format=rgba,"
        "colorkey=0x000000:0.025:0.22,unpremultiply=inplace=1[fg];"
        "[bg][fg]overlay=x=0:y=0:eof_action=pass:repeatlast=0:format=yuv420[composed];"
        "[2:a]atrim=duration=300,asetpts=PTS-STARTPTS,volume=-2dB,"
        "afade=t=in:st=0:d=0.08,afade=t=out:st=299.4:d=0.6[audio];"
        + opening_filter()
    )


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def composite(background: Path, objects: Path, music: Path, output: Path) -> dict:
    background_info = inspect_video(background)
    object_info = inspect_video(objects)
    if output.resolve() in {background.resolve(), objects.resolve(), music.resolve()}:
        raise ValueError("출력 경로는 입력 레이어와 달라야 합니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(f"{output.stem}.part-{uuid.uuid4().hex}.mp4")
    ffmpeg = find_ffmpeg()
    run([
        ffmpeg, "-y", "-v", "error", "-stats_period", "10", "-progress", "pipe:1",
        "-filter_complex_threads", "4", "-i", str(background), "-i", str(objects), "-i", str(music),
        "-filter_complex", composition_filter(), "-map", "[video]", "-map", "[audio]",
        "-r", "30", "-fps_mode", "cfr", "-t", "300",
        *delivery_video_args(), "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
        "-movflags", "+faststart", str(pending),
    ])
    check = subprocess.run(
        [ffmpeg, "-v", "error", "-xerror", "-threads", "4", "-i", str(pending), "-f", "null", "-"],
        capture_output=True,
    )
    if check.returncode or check.stderr:
        raise RuntimeError("통합 영상 디코딩 검사 실패: " + check.stderr.decode(errors="replace")[:1000])
    final_info = inspect_video(pending)
    pending.replace(output)
    report = dict(
        version="team4_v13_gridmodel_20261101", output=str(output), **final_info,
        full_decode_passed=True, background_source_mix=0.0,
        opening=dict(mode="generated_from_current_layers", blackout_until_seconds=0.8,
                     spread_start_seconds=5, transition_start_seconds=14, end_seconds=18),
        encoder=DELIVERY_ENCODER, audio_headroom_db=2.0,
        background=dict(path=str(background), sha256=sha256(background), **background_info),
        objects=dict(path=str(objects), sha256=sha256(objects), **object_info),
        music=dict(path=str(music), sha256=sha256(music)),
        video_sha256=sha256(output), filter_graph=composition_filter(),
    )
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def apply_opening(original: Path, opening: Path, output: Path) -> dict:
    """Keep the supplied point opening, then return to the completed video."""
    original, opening, output = (p.resolve() for p in (original, opening, output))
    if output in (original, opening):
        raise ValueError('수정본은 원본과 다른 새 파일 경로로 지정해 주세요.')
    info = inspect_video(original)
    inspect_video(opening)
    ffmpeg = find_ffmpeg()
    log = subprocess.run([ffmpeg, '-hide_banner', '-skip_frame', 'nokey', '-i', str(original),
                          '-an', '-vf', 'showinfo', '-f', 'null', '-'], capture_output=True, check=True).stderr
    keys = [round(float(t) * FPS) for t in re.findall(rb'pts_time:([0-9.]+)', log)]
    cut_frame = next((f for f in keys if f >= 18 * FPS), info['frames'])
    cut = cut_frame / FPS
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.opening-', dir=output.parent) as temp:
        work = Path(temp).resolve()
        assert work.parent == output.parent
        prefix, pending = work / 'prefix.mp4', work / 'result.mp4'
        graph = ('[0:v]trim=end=18,settb=1/30,setpts=N,fps=30[intro];'
                 f'[1:v]trim=start=14:end={cut:.9f},settb=1/30,setpts=N,fps=30[rest];'
                 '[intro][rest]xfade=transition=fade:duration=4:offset=14,format=yuv420p[video]')
        run([ffmpeg, '-y', '-v', 'error', '-i', str(opening), '-i', str(original),
             '-filter_complex_threads', '3', '-filter_complex', graph,
             '-map', '[video]', '-map', '1:a:0', '-frames:v', str(cut_frame), '-t', f'{cut:.9f}',
             *delivery_video_args(), '-r', '30', '-video_track_timescale', '15360',
             '-c:a', 'copy', '-movflags', '+faststart', str(prefix)])
        quote = lambda p: "'" + p.as_posix().replace("'", "'\\''") + "'"
        listing = work / 'join.ffconcat'
        entries = f'ffconcat version 1.0\nfile {quote(prefix)}\nduration {cut:.9f}\n'
        if cut_frame < info['frames']:
            entries += f'file {quote(original)}\ninpoint {cut:.9f}\noutpoint {DURATION}\n'
        listing.write_text(entries, encoding='utf-8')
        run([ffmpeg, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
             '-i', str(original), '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy',
             '-t', str(DURATION), '-movflags', '+faststart', str(pending)])
        check = subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-i', str(pending), '-f', 'null', '-'], capture_output=True, check=True)
        if check.stderr or inspect_video(pending) != info:
            raise RuntimeError('수정 영상의 디코딩 또는 프레임 검증에 실패했습니다.')
        audio_hash = lambda p: subprocess.check_output([ffmpeg, '-v', 'error', '-i', str(p),
            '-map', '0:a:0', '-c:a', 'copy', '-f', 'hash', '-hash', 'sha256', '-'])
        if audio_hash(original) != audio_hash(pending):
            raise RuntimeError('원본 사운드 보존 검사에 실패했습니다.')
        report = dict(**info, opening_until_seconds=14, transition_end_seconds=18,
                      stream_copy_from_seconds=cut, original_audio_preserved=True,
                      full_decode_passed=True, video_sha256=sha256(pending))
        pending.replace(output)
        output.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="DreamModel v13 + GridModel + sound")
    parser.add_argument("--background-layer", type=Path, help="Reuse an explicitly selected, already rendered v13 layer")
    parser.add_argument("--object-layer", type=Path, help="Reuse an explicitly selected GridModel layer")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "team4_output.mp4")
    parser.add_argument('--opening-video', type=Path, help='기존 완성본을 수동 편집할 때만 지정')
    parser.add_argument('--existing-video', type=Path, help='기존 완성본의 도입부만 수정')
    args = parser.parse_args()
    if args.existing_video:
        if args.opening_video is None:
            parser.error('--existing-video 수동 편집에는 --opening-video가 필요합니다.')
        apply_opening(args.existing_video, args.opening_video, args.output)
        return
    if args.opening_video is not None:
        parser.error('--opening-video는 --existing-video 수동 편집에만 사용합니다.')
    check_model_environment()
    validate_metadata()
    source = find_background_video()
    inspect_video(source, rendered_layer=False)
    music = find_music()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    background = args.background_layer or OUTPUT_DIR / "dreammodel_background_v13.mp4"
    objects = args.object_layer or OUTPUT_DIR / "gridmodel_object_ca.mp4"
    if args.background_layer is None:
        run(background_command(source), cwd=TEAM4_DIR.parent)
    if args.object_layer is None:
        run([str(PYTHON_EXE), str(GRID_SCRIPT)])
    composite(background.resolve(), objects.resolve(), music.resolve(), args.output.resolve())
    print(f"[완료] 통합 영상: {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
