"""Media inspection (ffprobe) and fitting videos under Telegram's size limit (ffmpeg)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .errors import Failed, TooLarge
from .proc import ProcRunner, run

TELEGRAM_MAX_BYTES = 50 * 1024 * 1024
PHOTO_MAX_BYTES = 10 * 1024 * 1024
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic"}
VIDEO_EXTS = {"mp4", "mov", "webm", "mkv", "m4v"}
_MIN_VIDEO_KBPS = 200
_AUDIO_KBPS = 128


def kind_for_path(path: Path) -> Literal["video", "image"] | None:
    ext = path.suffix.lower().lstrip(".")
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


@dataclass
class Probe:
    width: int | None
    height: int | None
    duration: float | None
    has_audio: bool


async def probe(path: Path, proc_run: ProcRunner = run) -> Probe:
    res = await proc_run(["ffprobe", "-v", "error", "-print_format", "json",
                          "-show_streams", "-show_format", str(path)], 30)
    if res.returncode != 0:
        raise Failed(f"couldn't read media file ({res.stderr.strip()[:80]})")
    data = json.loads(res.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    duration = data.get("format", {}).get("duration") or video.get("duration")
    return Probe(
        width=video.get("width"),
        height=video.get("height"),
        duration=float(duration) if duration not in (None, "N/A") else None,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def video_bitrate_kbps(limit_bytes: int, duration_s: float, audio_kbps: int = _AUDIO_KBPS,
                       margin: float = 0.92) -> int:
    """Video bitrate (kbit/s) that keeps a `duration_s` clip under `limit_bytes`."""
    total_kbps = limit_bytes * 8 * margin / duration_s / 1000
    return int(total_kbps - audio_kbps)


async def fit_video(path: Path, duration: float, limit: int = TELEGRAM_MAX_BYTES,
                    proc_run: ProcRunner = run) -> Path:
    """Return `path` if small enough, else a re-encoded copy under `limit` (original deleted)."""
    size = path.stat().st_size
    if size <= limit:
        return path
    kbps = video_bitrate_kbps(limit, max(duration, 1.0))
    if kbps < _MIN_VIDEO_KBPS:
        raise TooLarge(size)
    out = path.with_name(f"{path.stem}.fit.mp4")
    res = await proc_run([
        "ffmpeg", "-v", "error", "-y", "-i", str(path),
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{2 * kbps}k",
        "-c:a", "aac", "-b:a", f"{_AUDIO_KBPS}k", "-movflags", "+faststart", str(out),
    ], 900)
    if res.returncode != 0 or not out.exists() or out.stat().st_size > limit:
        out.unlink(missing_ok=True)
        raise TooLarge(size)
    path.unlink()
    return out
