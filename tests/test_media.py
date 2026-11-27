import subprocess
from pathlib import Path

import pytest

from bot.engine.errors import TooLarge
from bot.engine.media import (
    PHOTO_MAX_BYTES, TELEGRAM_MAX_BYTES, fit_video, kind_for_path, probe, video_bitrate_kbps,
)


@pytest.fixture
def make_video(tmp_path):
    counter = iter(range(1000))

    def _make(seconds=2, bitrate="500k", size="320x240", audio=True):
        out = tmp_path / f"v{next(counter)}.mp4"
        args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={seconds}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
        args += ["-c:v", "libx264", "-b:v", bitrate, "-minrate", bitrate, "-maxrate", bitrate,
                 "-bufsize", bitrate, "-x264-params", "nal-hrd=cbr", "-pix_fmt", "yuv420p", str(out)]
        subprocess.run(args, check=True)
        return out
    return _make


def test_limits():
    assert TELEGRAM_MAX_BYTES == 50 * 1024 * 1024
    assert PHOTO_MAX_BYTES == 10 * 1024 * 1024


def test_bitrate_math():
    assert video_bitrate_kbps(50 * 1024 * 1024, 60) == 6303
    assert video_bitrate_kbps(50 * 1024 * 1024, 3600) < 0


def test_kind_for_path():
    assert kind_for_path(Path("a.JPG")) == "image"
    assert kind_for_path(Path("a.webp")) == "image"
    assert kind_for_path(Path("a.mp4")) == "video"
    assert kind_for_path(Path("a.json")) is None
    assert kind_for_path(Path("noext")) is None


async def test_probe_real_file(make_video):
    p = await probe(make_video(seconds=2, bitrate="500k", size="320x240"))
    assert (p.width, p.height, p.has_audio) == (320, 240, True)
    assert 1.5 < p.duration < 2.5


async def test_probe_silent(make_video):
    assert (await probe(make_video(seconds=1, audio=False))).has_audio is False


async def test_probe_image(tmp_path):
    img = tmp_path / "i.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x48", "-frames:v", "1", str(img)], check=True)
    p = await probe(img)
    assert (p.width, p.height, p.has_audio) == (64, 48, False)


async def test_fit_video_noop_under_limit(make_video):
    v = make_video(seconds=1, bitrate="200k")
    assert await fit_video(v, 1.0, limit=10_000_000) == v


async def test_fit_video_reencodes_under_limit(make_video):
    v = make_video(seconds=2, bitrate="5M")
    assert v.stat().st_size > 500_000
    out = await fit_video(v, 2.0, limit=500_000)
    assert out.stat().st_size <= 500_000
    assert not v.exists()


async def test_fit_video_too_long_raises(make_video):
    v = make_video(seconds=1, bitrate="5M")
    with pytest.raises(TooLarge):
        await fit_video(v, 3600.0, limit=500_000)
