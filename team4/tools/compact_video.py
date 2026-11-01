"""Compress an existing 300-second integrated movie without regenerating its scenes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from team4.main import find_ffmpeg, inspect_video, run, sha256
from team4.video_encoding import DELIVERY_ENCODER, delivery_video_args


def main() -> None:
    parser = argparse.ArgumentParser(description="Compress an existing 1080p30 Team4 final; copy audio unchanged")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if source == output:
        raise ValueError("Choose a separate output to preserve the source master.")
    source_info = inspect_video(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(f"{output.stem}.part-{uuid.uuid4().hex}.mp4")
    ffmpeg = find_ffmpeg()
    run([
        ffmpeg, "-y", "-v", "error", "-stats_period", "10", "-progress", "pipe:1",
        "-threads", "4", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0",
        *delivery_video_args(), "-fps_mode", "passthrough", "-c:a", "copy",
        "-movflags", "+faststart", str(pending),
    ])
    check = subprocess.run([ffmpeg, "-v", "error", "-xerror", "-threads", "4", "-i", str(pending),
                            "-f", "null", "-"], capture_output=True)
    if check.returncode or check.stderr:
        raise RuntimeError("Decode verification failed: " + check.stderr.decode(errors="replace")[:1000])
    output_info = inspect_video(pending)
    if pending.stat().st_size > 1_000_000_000:
        raise RuntimeError("Delivery exceeded the 1 GB size budget; inspect the encode before publishing.")
    pending.replace(output)
    report = dict(version="team4_v13_compact_delivery", source=str(source), output=str(output),
                  source_video=source_info, **output_info, encoder=DELIVERY_ENCODER,
                  source_bytes=source.stat().st_size, bytes=output.stat().st_size,
                  size_reduction_percent=round(100*(1-output.stat().st_size/source.stat().st_size),2),
                  audio_mode="stream_copy", full_decode_passed=True,
                  source_sha256=sha256(source), video_sha256=sha256(output),
                  content_unchanged=True, pixel_identical=False)
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
