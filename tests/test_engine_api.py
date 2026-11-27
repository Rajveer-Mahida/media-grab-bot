from pathlib import Path

import httpx
import pytest

from bot.engine import download
from bot.engine.errors import InstagramPaused, NoCookies, RateLimited, TooLarge, Unsupported, scrub
from bot.engine.media import TELEGRAM_MAX_BYTES, Probe
from bot.engine.models import MediaItem, Result

IG_REEL = "https://www.instagram.com/reel/R1/"
IG_SHARE = "https://www.instagram.com/share/reel/S1/"
X_STATUS = "https://x.com/u/status/9"
SESSION = "123456%3AsessionSECRETvalue"
COOKIES = (
    "# Netscape HTTP Cookie File\n"
    f".instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\t{SESSION}\n"
    ".instagram.com\tTRUE\t/\tTRUE\t1999999999\tcsrftoken\tcsrfSECRETvalue\n"
)


class FakePacer:
    def __init__(self, paused=0.0):
        self.paused = paused
        self.waits = 0
        self.pauses = []

    async def wait(self):
        self.waits += 1

    def pause(self, seconds=600):
        self.pauses.append(seconds)

    def paused_for(self):
        return self.paused


class Recorder:
    def __init__(self, result=None, exc=None):
        self.calls = []
        self.result, self.exc = result, exc

    async def __call__(self, ref, workdir, *rest):
        self.calls.append((ref, rest))
        if self.exc:
            raise self.exc
        return self.result


def item(tmp_path, name="a.mp4", kind="video", size=100):
    p = tmp_path / name
    p.write_bytes(b"x")
    return MediaItem(path=p, kind=kind, size=size)


@pytest.fixture
def cookies(tmp_path):
    p = tmp_path / "ig.cookies.txt"
    p.write_text(COOKIES)
    return p


@pytest.fixture
def http():
    def handler(request):
        if str(request.url) == IG_SHARE:
            return httpx.Response(302, headers={"Location": IG_REEL})
        raise AssertionError(f"unexpected {request.url}")
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def prober_sound(path):
    return Probe(720, 1280, 12.5, True)


async def prober_silent(path):
    return Probe(480, 480, 4.0, False)


def kwargs(tmp_path, cookies, http, pacer, **over):
    base = dict(cookies=cookies, pacer=pacer, http=http, prober=prober_sound)
    base.update(over)
    return base


async def test_unsupported(tmp_path, cookies, http):
    with pytest.raises(Unsupported):
        await download("https://example.com/x", tmp_path, **kwargs(tmp_path, cookies, http, FakePacer()))


async def test_instagram_without_cookie_file_raises_nocookies(tmp_path, http):
    ig = Recorder()
    pacer = FakePacer()
    with pytest.raises(NoCookies):
        await download(IG_REEL, tmp_path, **kwargs(tmp_path, tmp_path / "missing.txt", http, pacer, ig=ig))
    assert ig.calls == [] and pacer.waits == 0


async def test_paused_instagram_fails_fast(tmp_path, cookies, http):
    ig, pacer = Recorder(), FakePacer(paused=120)
    with pytest.raises(InstagramPaused) as e:
        await download(IG_REEL, tmp_path, **kwargs(tmp_path, cookies, http, pacer, ig=ig))
    assert e.value.seconds == 120 and ig.calls == [] and pacer.waits == 0


async def test_instagram_waits_once_including_share_resolution(tmp_path, cookies, http):
    ig = Recorder(Result([item(tmp_path)], "u", IG_REEL))
    pacer = FakePacer()
    r = await download(IG_SHARE, tmp_path, **kwargs(tmp_path, cookies, http, pacer, ig=ig))
    assert pacer.waits == 1
    ref, rest = ig.calls[0]
    assert ref.url == IG_REEL and rest == (cookies,)
    assert (r.items[0].width, r.items[0].height, r.items[0].duration) == (720, 1280, 12.5)


async def test_ratelimit_pauses_pacer(tmp_path, cookies, http):
    pacer = FakePacer()
    with pytest.raises(RateLimited):
        await download(IG_REEL, tmp_path, **kwargs(tmp_path, cookies, http, pacer, ig=Recorder(exc=RateLimited())))
    assert pacer.pauses == [600]


async def test_x_does_not_touch_pacer_or_cookies(tmp_path, http):
    x = Recorder(Result([item(tmp_path)], "u", X_STATUS))
    pacer = FakePacer(paused=300)
    await download(X_STATUS, tmp_path, **kwargs(tmp_path, tmp_path / "missing.txt", http, pacer, x=x))
    assert pacer.waits == 0 and x.calls[0][1] == ()


async def test_x_silent_video_becomes_gif(tmp_path, cookies, http):
    x = Recorder(Result([item(tmp_path)], "u", X_STATUS))
    r = await download(X_STATUS, tmp_path, **kwargs(tmp_path, cookies, http, FakePacer(), x=x, prober=prober_silent))
    assert r.items[0].kind == "gif" and r.items[0].has_audio is False


async def test_instagram_silent_video_stays_video(tmp_path, cookies, http):
    ig = Recorder(Result([item(tmp_path)], "u", IG_REEL))
    r = await download(IG_REEL, tmp_path, **kwargs(tmp_path, cookies, http, FakePacer(), ig=ig, prober=prober_silent))
    assert r.items[0].kind == "video"


async def test_oversized_video_is_fitted(tmp_path, cookies, http):
    big = item(tmp_path, size=60 * 1024 * 1024)
    original = big.path
    fitted = tmp_path / "a.fit.mp4"
    fitted.write_bytes(b"y" * 7)
    calls = []

    async def fitter(path, duration):
        calls.append((path, duration))
        return fitted

    x = Recorder(Result([big], "u", X_STATUS))
    r = await download(X_STATUS, tmp_path, **kwargs(tmp_path, cookies, http, FakePacer(), x=x, fitter=fitter))
    assert calls == [(original, 12.5)]
    assert r.items[0].path == fitted and r.items[0].size == 7


async def test_oversized_image_raises(tmp_path, cookies, http):
    x = Recorder(Result([item(tmp_path, "a.jpg", "image", TELEGRAM_MAX_BYTES + 1)], "u", X_STATUS))
    with pytest.raises(TooLarge):
        await download(X_STATUS, tmp_path, **kwargs(tmp_path, cookies, http, FakePacer(), x=x))


async def test_cookie_values_registered(tmp_path, cookies, http):
    ig = Recorder(Result([item(tmp_path, "a.jpg", "image")], "u", IG_REEL))
    await download(IG_REEL, tmp_path, **kwargs(tmp_path, cookies, http, FakePacer(), ig=ig))
    assert scrub(f"x {SESSION} csrfSECRETvalue") == "x *** ***"
