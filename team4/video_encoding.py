"""Shared H.264 delivery settings for Team4's five-minute output."""

DELIVERY_ENCODER = {
    "codec": "libx264", "preset": "medium", "crf": 20,
    "pixel_format": "yuv420p",
}


def delivery_video_args(threads: int = 6) -> list[str]:
    """Keep 1080p detail with CRF; allow dense cells temporary bitrate peaks."""
    return [
        "-c:v", DELIVERY_ENCODER["codec"], "-threads", str(threads),
        "-preset", DELIVERY_ENCODER["preset"], "-crf", str(DELIVERY_ENCODER["crf"]),
        "-pix_fmt", DELIVERY_ENCODER["pixel_format"],
    ]
