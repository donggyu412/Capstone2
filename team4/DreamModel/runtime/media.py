"""Streaming H.264 encoding and original-clock audio excerpts."""
from __future__ import annotations
import os, shutil, subprocess, tempfile, wave
from pathlib import Path
from typing import Any
import numpy as np

def find_ffmpeg() -> str:
    """Find a system encoder or the executable supplied by imageio-ffmpeg."""
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError(
            "FFmpeg is unavailable. Install DreamModel/requirements.txt in the "
            "Python environment used to run this command."
        ) from exc

def subprocess_options() -> dict[str, Any]:
    """Keep encoder/decoder helpers invisible when launched on Windows."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

class VideoWriter:
    """Stream RGB frames into H.264; publish only a successfully closed MP4.

    Existing output is preserved if encoding fails. No frames are collected in
    memory. Optional audio is padded with silence or truncated to video length.
    """

    def __init__(self, path: Path | str, width: int, height: int, fps: int,
                 *, audio_path: Path | str | None = None, expected_frames: int | None = None,
                 ffmpeg_path: str | None = None, crf: int = 20,
                 keyframe_interval: int | None = None) -> None:
        if width < 2 or height < 2 or width % 2 or height % 2 or fps < 1:
            raise ValueError("H.264 yuv420p requires positive even dimensions and positive fps")
        if expected_frames is not None and expected_frames < 1:
            raise ValueError("expected_frames must be positive")
        if not 0 <= crf <= 51 or (keyframe_interval is not None and keyframe_interval < 1):
            raise ValueError('Invalid H.264 quality or keyframe interval')
        self.path = Path(path)
        self.width, self.height, self.fps = width, height, fps
        self.expected_frames, self.frame_count = expected_frames, 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        audio = Path(audio_path).resolve() if audio_path is not None else None
        if audio is not None and not audio.is_file():
            raise FileNotFoundError(f"Audio file does not exist: {audio}")
        executable = ffmpeg_path or find_ffmpeg()
        handle, temporary_path = tempfile.mkstemp(prefix=f".{self.path.stem}-", suffix=".mp4", dir=self.path.parent)
        os.close(handle)
        self._temporary = Path(temporary_path)
        self._errors = tempfile.TemporaryFile()
        self._closed = False
        command = [executable, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
                   "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                   "-r", str(fps), "-i", "pipe:0"]
        if audio is not None:
            command += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                        "-af", "apad", "-c:a", "aac", "-b:a", "128k", "-shortest"]
        else:
            command += ["-an"]
        command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart"]
        if keyframe_interval is not None:
            command += ['-g',str(keyframe_interval),'-keyint_min',str(keyframe_interval),'-sc_threshold','0']
        if expected_frames is not None:
            command += ["-t", f"{expected_frames / fps:.9f}"]
        command += [str(self._temporary)]
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=self._errors, **subprocess_options())
        except BaseException:
            self._errors.close()
            self._temporary.unlink(missing_ok=True)
            raise

    def __enter__(self) -> "VideoWriter":
        return self

    def _diagnostic(self) -> str:
        self._errors.seek(0)
        return self._errors.read().decode("utf-8", errors="replace").strip()[-4000:]

    def write(self, frame: np.ndarray) -> None:
        if self._closed:
            raise RuntimeError("Cannot write after video is closed")
        if frame.shape != (self.height, self.width, 3) or frame.dtype != np.uint8:
            raise ValueError("Video frames must match writer dimensions as uint8 RGB")
        if self.expected_frames is not None and self.frame_count >= self.expected_frames:
            raise ValueError("More frames supplied than expected_frames")
        try:
            self._process.stdin.write(np.ascontiguousarray(frame).tobytes())
        except (BrokenPipeError, OSError) as exc:
            self._process.wait()
            message = self._diagnostic()
            self.abort()
            raise RuntimeError(f"FFmpeg failed while writing video: {message}") from exc
        self.frame_count += 1

    def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait()
        try:
            self._process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        self._errors.close()
        self._temporary.unlink(missing_ok=True)

    def close(self) -> Path:
        if self._closed:
            return self.path
        if self.frame_count == 0 or (self.expected_frames is not None and self.frame_count != self.expected_frames):
            self.abort()
            raise ValueError(f"Video frame count {self.frame_count} does not match {self.expected_frames}")
        try:
            self._process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        code = self._process.wait()
        message = self._diagnostic()
        self._errors.close()
        self._closed = True
        if code != 0:
            self._temporary.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg exited with status {code}: {message}")
        os.replace(self._temporary, self.path)
        return self.path

    def __exit__(self, exception_type: Any, exception: Any, traceback: Any) -> bool:
        if exception_type is None:
            self.close()
        else:
            self.abort()
        return False

def prepare_audio(source,destination,start=65.,duration=20.):
    if source is None:return None,{'status':'no supplied audio'}
    rate=44100
    command=[find_ffmpeg(),'-hide_banner','-loglevel','error','-ss',str(start),'-i',str(source),
             '-t',str(duration),'-ac','2','-ar',str(rate),'-f','f32le','pipe:1']
    result=subprocess.run(command,capture_output=True,**subprocess_options())
    if result.returncode:raise ValueError(result.stderr.decode('utf-8',errors='replace'))
    samples=np.frombuffer(result.stdout,dtype='<f4').reshape(-1,2)
    if len(samples)<round(duration*rate):raise ValueError('Audio is shorter than the requested original-time window')
    samples=samples[:round(duration*rate)].copy()
    fade=round(.02*rate)
    samples[:fade]*=np.linspace(0,1,fade)[:,None];samples[-fade:]*=np.linspace(1,0,fade)[:,None]
    destination.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(destination),'wb') as out:
        out.setnchannels(2);out.setsampwidth(2);out.setframerate(rate)
        out.writeframes((np.clip(samples,-1,1)*32767).astype('<i2').tobytes())
    return destination,{'source':str(source),'source_start':start,'source_end':start+duration,
        'playback_rate':1.,'time_stretch':False,'scene_splice':False,'edge_fade_seconds':.02}
