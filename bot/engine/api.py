"""The engine entry point: one link in, downloaded media out."""
from __future__ import annotations

from pathlib import Path

import httpx

import shutil

from .errors import DownloadError, InstagramPaused, NoCookies, RateLimited, TooLarge, Unsupported, register_secret
from .instagram import download_instagram
from .media import TELEGRAM_MAX_BYTES, fit_video, probe
from .models import LinkRef, Platform, Result
from .pacing import Pacer
from .urls import classify_url, resolve
from .x import download_x

RATE_LIMIT_PAUSE_S = 600


def _register_cookie_values(cookies: Path) -> None:
    try:
        text = cookies.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) == 7 and not line.startswith("# "):
            register_secret(fields[6].strip())


async def download(url: str, workdir: Path, *, cookies: Path, pacer: Pacer, http: httpx.AsyncClient,
                   ig=download_instagram, x=download_x, prober=probe, fitter=fit_video) -> Result:
    ref = classify_url(url)
    if ref is None:
        raise Unsupported()

    waited = False

    async def instagram_gate() -> None:
        nonlocal waited
        remaining = pacer.paused_for()
        if remaining > 0:
            raise InstagramPaused(remaining)
        if cookies.is_file():
            _register_cookie_values(cookies)
        if not waited:
            await pacer.wait()
            waited = True

    if ref.platform is Platform.INSTAGRAM:
        if ref.kind == "story" and not cookies.is_file():
            raise NoCookies()
        await instagram_gate()
    if ref.kind == "short":
        ref = await resolve(ref, http)
        if ref.platform is Platform.INSTAGRAM:
            await instagram_gate()

    result = await _dispatch(ref, workdir, cookies, pacer, ig, x)
    for item in result.items:
        if item.kind == "image":
            if item.size > TELEGRAM_MAX_BYTES:
                raise TooLarge(item.size)
            continue
        info = await prober(item.path)
        item.width, item.height, item.duration, item.has_audio = (
            info.width, info.height, info.duration, info.has_audio)
        if ref.platform is Platform.X and not info.has_audio:
            item.kind = "gif"
        if item.size > TELEGRAM_MAX_BYTES:
            item.path = await fitter(item.path, info.duration or 0.0)
            item.size = item.path.stat().st_size
    return result


async def _dispatch(ref: LinkRef, workdir: Path, cookies: Path, pacer: Pacer, ig, x) -> Result:
    if ref.platform is Platform.X:
        return await x(ref, workdir)
    try:
        return await _instagram(ref, workdir, cookies, pacer, ig)
    except RateLimited:
        pacer.pause(RATE_LIMIT_PAUSE_S)
        raise


async def _instagram(ref: LinkRef, workdir: Path, cookies: Path, pacer: Pacer, ig) -> Result:
    """Public content is tried logged out first (no account risk); the owner's cookies are
    used only when that fails. Stories always need a login."""
    if ref.kind == "story":
        if not cookies.is_file():
            raise NoCookies()
        return await ig(ref, workdir, cookies)
    try:
        return await ig(ref, workdir, None)
    except RateLimited:
        raise
    except DownloadError:
        if not cookies.is_file():
            raise NoCookies() from None
    _empty_dir(workdir)
    await pacer.wait()
    return await ig(ref, workdir, cookies)


def _empty_dir(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
