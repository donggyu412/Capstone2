"""Run DreamModel and GridModel, then composite their layers."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


TEAM4_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = TEAM4_DIR / "output"
SOUND_DIR = TEAM4_DIR / "input" / "sound"
BACKGROUND_DIR = TEAM4_DIR / "input" / "background"
GRID_SCRIPT = TEAM4_DIR / "Grid_Model" / "GridModel" / "pythonimagemodel.py"
MODEL_PYTHON = TEAM4_DIR / "DreamModel" / ".venv" / "Scripts" / "python.exe"
PYTHON_EXE = MODEL_PYTHON if MODEL_PYTHON.exists() else Path(sys.executable)
FILM = 1


def find_music() -> Path:
    supported = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
    tracks = sorted(p for p in SOUND_DIR.iterdir()
                    if p.is_file() and p.suffix.lower() in supported)
    if not tracks:
        raise FileNotFoundError(f"input/sound에 사용할 음악 파일이 없습니다: {SOUND_DIR}")
    if len(tracks) > 1:
        print(f"[main] 여러 음악 중 첫 파일 사용: {tracks[0].name}")
    return tracks[0]


def find_background_video() -> Path:
    supported = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    videos = sorted(p for p in BACKGROUND_DIR.iterdir()
                    if p.is_file() and p.suffix.lower() in supported)
    if not videos:
        raise FileNotFoundError(f"input/background에 배경 영상이 없습니다: {BACKGROUND_DIR}")
    if len(videos) > 1:
        names = ", ".join(p.name for p in videos)
        raise RuntimeError(
            f"input/background에는 배경 영상 하나만 두어야 합니다. 현재 파일: {names}"
        )
    return videos[0]


def find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        result = subprocess.run(
            [str(PYTHON_EXE), "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
            check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()
    except Exception as exc:
        raise RuntimeError("FFmpeg를 찾을 수 없습니다. DreamModel 실행 환경을 확인해 주세요.") from exc


def run(command: list[str], *, cwd: Path) -> None:
    print("[main] 실행:", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def check_model_environment() -> None:
    result = subprocess.run(
        [str(PYTHON_EXE), "-c", "import torch, cv2, numpy"],
        capture_output=True, text=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else "필수 모듈을 불러오지 못했습니다."
        raise SystemExit(
            f"[환경 오류] 모델 Python에서 필수 패키지를 찾지 못했습니다: {reason}\n"
            f"사용 Python: {PYTHON_EXE}\n"
            "Python 3.12 환경을 만들고 torch, opencv-python, numpy를 설치한 뒤 다시 실행해 주세요."
        )


def make_dreammodel_storyboard(video_path: Path, target_dir: Path) -> None:
    """Sample four representative frames for DreamModel's existing plate input."""
    import cv2

    template_dir = TEAM4_DIR / "DreamModel" / "configs" / "scenarios" / "1_놀람공포중립공포"
    for metadata_name in ("scenes.json", "dream_scenes.json"):
        metadata = template_dir / metadata_name
        if not metadata.is_file():
            raise FileNotFoundError(f"DreamModel 장면 설정 파일이 없습니다: {metadata}")
        shutil.copy2(metadata, target_dir / metadata_name)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"배경 영상을 열 수 없습니다: {video_path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count < 4:
            raise RuntimeError(f"배경 영상의 프레임 수가 부족합니다: {frame_count}")
        for index, fraction in enumerate((0.10, 0.35, 0.65, 0.90), start=1):
            frame_number = min(frame_count - 1, int(frame_count * fraction))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError(f"배경 영상에서 장면 프레임을 읽지 못했습니다: {frame_number}")
            output_path = target_dir / f"scene_{index:02d}.png"
            if not cv2.imwrite(str(output_path), frame):
                raise RuntimeError(f"DreamModel 입력 프레임을 저장하지 못했습니다: {output_path}")
    finally:
        capture.release()


def main() -> None:
    check_model_environment()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    background_video = find_background_video()
    music = find_music()
    background_layer = OUTPUT_DIR / f"{FILM}번_꿈재현_배경_v3_사운드.mp4"
    object_video = OUTPUT_DIR / "gridmodel_object_ca.mp4"
    final_video = OUTPUT_DIR / "team4_output.mp4"

    # DreamModel currently consumes four image plates plus scene metadata.
    # Sample those plates from the one supplied MP4, then call its existing CLI.
    with tempfile.TemporaryDirectory(prefix="dreammodel_storyboard_", dir=OUTPUT_DIR) as temp_dir:
        storyboard_dir = Path(temp_dir)
        make_dreammodel_storyboard(background_video, storyboard_dir)
        run([
            str(PYTHON_EXE), "-m", "team4.DreamModel.tools.render_background_ca",
            "--from-input", "--scenario-dir", str(storyboard_dir),
            "--film", str(FILM), "--sound", str(music),
            "--out-dir", str(OUTPUT_DIR),
        ], cwd=TEAM4_DIR.parent)

    if not background_layer.exists():
        raise FileNotFoundError(f"DreamModel 배경 결과가 없습니다: {background_layer}")

    # GridModel reads team4/input/object/object_line_1.mp4 and writes its layer
    # into team4/output via its local config.py.
    run([str(PYTHON_EXE), str(GRID_SCRIPT)], cwd=TEAM4_DIR)

    if not object_video.exists():
        raise FileNotFoundError(f"GridModel 오브제 결과가 없습니다: {object_video}")

    ffmpeg = find_ffmpeg()
    # GridModel's black canvas is keyed out over DreamModel's generated background.
    filter_graph = (
        "[1:v]colorkey=0x000000:0.12:0.06[object];"
        "[0:v][object]overlay=shortest=1,format=yuv420p[video]"
    )
    run([
        ffmpeg, "-y", "-v", "error",
        "-i", str(background_layer), "-i", str(object_video),
        "-filter_complex", filter_graph,
        "-map", "[video]", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy", "-t", "300", "-movflags", "+faststart",
        str(final_video),
    ], cwd=TEAM4_DIR)

    # Keep only the integrated deliverable; these are regenerable intermediate layers.
    background_layer.unlink(missing_ok=True)
    object_video.unlink(missing_ok=True)
    print(f"[완료] 통합 영상: {final_video}", flush=True)


if __name__ == "__main__":
    main()
