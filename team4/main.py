"""Render v13 background and GridModel, then composite on one 300-second clock."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
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


def composition_filter() -> str:
    # Only the object's black canvas is removed. Background pixels are not
    # resized, blurred, graded, or blended with the Team3 source video.
    # The source's antialiased edge colors include the black canvas. Recover
    # straight RGB after a gradual key so those edges do not become dark halos.
    return (
        "[0:v]setpts=PTS-STARTPTS[bg];"
        "[1:v]fps=30,setpts=N/(30*TB),format=rgba,"
        "colorkey=0x000000:0.025:0.22,unpremultiply=inplace=1[fg];"
        "[bg][fg]overlay=x=0:y=0:eof_action=pass:repeatlast=0:format=yuv420[video];"
        "[2:a]atrim=duration=300,asetpts=PTS-STARTPTS,volume=-2dB,"
        "afade=t=in:st=0:d=0.08,afade=t=out:st=299.4:d=0.6[audio]"
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
        encoder=DELIVERY_ENCODER, audio_headroom_db=2.0,
        background=dict(path=str(background), sha256=sha256(background), **background_info),
        objects=dict(path=str(objects), sha256=sha256(objects), **object_info),
        music=dict(path=str(music), sha256=sha256(music)),
        video_sha256=sha256(output), filter_graph=composition_filter(),
    )
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="DreamModel v13 + GridModel + sound")
    parser.add_argument("--background-layer", type=Path, help="Reuse an explicitly selected, already rendered v13 layer")
    parser.add_argument("--object-layer", type=Path, help="Reuse an explicitly selected GridModel layer")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "team4_output.mp4")
    args = parser.parse_args()
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
