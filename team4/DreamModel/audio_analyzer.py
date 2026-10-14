"""Optional audio amplitude measurement; no emotion or narrative inference."""

from __future__ import annotations

from pathlib import Path
import subprocess

import numpy as np

try:
    from .frame_renderer import find_ffmpeg, subprocess_options
except ImportError:
    from frame_renderer import find_ffmpeg, subprocess_options


class AudioAnalyzer:
    """Decode supplied audio once, then sample normalized, smoothed short RMS.

    Missing optional audio is represented explicitly by ``path=None``. An
    explicitly named but absent or undecodable file is an error, never silently
    treated as valid silent input. Samples beyond the recording are zero.
    """

    def __init__(self, path: Path | str | None = None, *, sample_rate: int = 16000,
                 window_seconds: float = .05, smoothing_seconds: float = .2,
                 ffmpeg_path: str | None = None) -> None:
        if sample_rate < 1000 or window_seconds <= 0 or smoothing_seconds < 0:
            raise ValueError("Invalid RMS sampling parameters")
        self.path = Path(path).resolve() if path is not None else None
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.smoothing_seconds = smoothing_seconds
        self.duration = 0.0
        self.rms_peak = 0.0
        self.values = np.zeros(1, dtype=np.float64)
        self.times = np.zeros(1, dtype=np.float64)
        if self.path is None:
            return
        if not self.path.is_file():
            raise FileNotFoundError(f"Audio file does not exist: {self.path}")
        command = [ffmpeg_path or find_ffmpeg(), "-hide_banner", "-loglevel", "error",
                   "-i", str(self.path), "-map", "0:a:0", "-vn", "-ac", "1",
                   "-ar", str(sample_rate), "-f", "f32le", "pipe:1"]
        result = subprocess.run(command, capture_output=True, **subprocess_options())
        if result.returncode:
            diagnostic = result.stderr.decode("utf-8", errors="replace").strip()[-2000:]
            raise ValueError(f"Cannot decode supplied audio {self.path.name}: {diagnostic}")
        samples = np.frombuffer(result.stdout, dtype="<f4")
        if not samples.size or not np.isfinite(samples).all():
            raise ValueError(f"Audio contains no finite PCM samples: {self.path}")
        self.duration = samples.size / sample_rate
        size = max(1, round(window_seconds * sample_rate))
        self.window_seconds = size / sample_rate
        count = (samples.size + size - 1) // size
        padded = np.zeros(count * size, dtype=np.float32)
        padded[:samples.size] = samples
        rms = np.sqrt(np.mean(np.square(padded.reshape(count, size), dtype=np.float64), axis=1))
        self.rms_peak = float(rms.max())
        positive = rms[rms > 1e-8]
        reference = float(np.percentile(positive, 95)) if positive.size else 0.0
        normalized = np.clip(rms / reference, 0, 1) if reference > 1e-8 else np.zeros_like(rms)
        decay = np.exp(-self.window_seconds / smoothing_seconds) if smoothing_seconds else 0.0
        values = np.zeros_like(normalized)
        previous = 0.0
        for index, value in enumerate(normalized):
            previous = decay * previous + (1 - decay) * value
            values[index] = previous
        self.values = values
        self.times = (np.arange(count, dtype=np.float64) + .5) * self.window_seconds

    def sample(self, time_seconds: float) -> float:
        if not np.isfinite(time_seconds):
            raise ValueError("Audio sample time must be finite")
        if self.path is None or time_seconds < 0 or time_seconds >= self.duration:
            return 0.0
        return float(np.interp(time_seconds, self.times, self.values))

    def as_report(self) -> dict[str, object]:
        return {
            "path": str(self.path) if self.path is not None else None,
            "duration_seconds": self.duration,
            "sample_rate": self.sample_rate,
            "rms_window_seconds": self.window_seconds,
            "smoothing_seconds": self.smoothing_seconds,
            "raw_rms_peak": self.rms_peak,
            "normalized_smoothed_peak": float(self.values.max()),
            "normalization": "95th percentile of non-silent short-window RMS; clipped to [0, 1]",
            "analysis": "amplitude only; no emotion inference",
        }

    def features(self, time_seconds: float) -> tuple[float, float]:
        """RMS and positive envelope change; neither implies an emotion."""
        rms = self.sample(time_seconds)
        onset = max(0.0, rms - self.sample(time_seconds - .12))
        return rms, min(1.0, onset * 4)


def prepare_preview_audio(source: Path | None, destination: Path, scene_seconds: float,
                          *, preview: bool) -> tuple[Path | None, dict]:
    """Match audible samples and modulation clock; never speed up the source.

    In the absence of an upstream cue sheet, four equal source sections are an
    explicit approximation. Select their central excerpts, padding only when
    the source is shorter than the requested preview.
    """
    if source is None:
        return None, {"source": None, "status": "missing; silent technical preview"}
    probe = AudioAnalyzer(source)
    if not preview:
        return source, {"source": str(source), "source_duration": probe.duration,
                        "timing": "original audio clock", "segments": []}
    import wave
    rate = 44100
    count = round(scene_seconds * rate)
    destination.parent.mkdir(parents=True, exist_ok=True)
    segments = []
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        for index in range(4):
            section = probe.duration / 4
            start = index * section + max(0, (section - scene_seconds) / 2)
            length = min(scene_seconds, section)
            command = [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.9f}",
                       "-i", str(source), "-t", f"{length:.9f}", "-map", "0:a:0", "-vn",
                       "-ac", "2", "-ar", str(rate), "-f", "f32le", "pipe:1"]
            decoded = subprocess.run(command, capture_output=True, **subprocess_options())
            if decoded.returncode:
                raise ValueError("Cannot prepare preview audio: " + decoded.stderr.decode("utf-8", errors="replace"))
            samples = np.frombuffer(decoded.stdout, dtype="<f4").reshape(-1, 2)[:count]
            excerpt = np.zeros((count, 2), dtype=np.float32)
            excerpt[:len(samples)] = samples
            fade = min(round(.025 * rate), len(samples)//2)
            if fade:
                excerpt[:fade] *= np.linspace(0, 1, fade)[:, None]
                excerpt[len(samples)-fade:len(samples)] *= np.linspace(1, 0, fade)[:, None]
            output.writeframes((np.clip(excerpt, -1, 1)*32767).astype("<i2").tobytes())
            segments.append({"scene_order": index+1, "source_start": start,
                             "source_end": start+length, "preview_start": index*scene_seconds,
                             "preview_end": (index+1)*scene_seconds})
    return destination, {"source": str(source), "source_duration": probe.duration,
                         "excerpt_file": str(destination), "segments": segments,
                         "timing": "central excerpts of four equal source sections; assumed scene alignment, no time stretch",
                         "cut_fade_seconds": .025}
