"""Instagram downloads via gallery-dl, with yt-dlp as fallback for reels/IGTV."""
from __future__ import annotations

from pathlib import Path

from .errors import Failed, LoginRequired, NotFound, classify
from .models import LinkRef, Platform, Result
from .proc import ProcRunner, run
from .tools import (
    DOWNLOAD_TIMEOUT, YTDLP_INSTAGRAM_EXTRACTORS, gallery_dl_args, parse_gallery_dl, parse_ytdlp, read_metadata_author, ytdlp_args,
)

_AUTHOR_KEYS = [("username",), ("owner_username",)]
_YTDLP_KINDS = ("reel", "tv", "post")


async def download_instagram(ref: LinkRef, workdir: Path, cookies: Path | None,
                             proc_run: ProcRunner = run) -> Result:
    res = await proc_run(gallery_dl_args(ref.url, workdir, cookies), DOWNLOAD_TIMEOUT)
    items = parse_gallery_dl(res.stdout, workdir)
    if items:
        return Result(items, read_metadata_author(workdir, _AUTHOR_KEYS), ref.url)
    if res.returncode == 0:
        raise NotFound()
    err = classify(Platform.INSTAGRAM, res.stderr)
    # Logged out, gallery-dl often gets 401 where yt-dlp still works for public videos.
    if not (isinstance(err, (Failed, LoginRequired)) and ref.kind in _YTDLP_KINDS):
        raise err

    res = await proc_run(ytdlp_args(ref.url, workdir, YTDLP_INSTAGRAM_EXTRACTORS, cookies), DOWNLOAD_TIMEOUT)
    items, author = parse_ytdlp(res.stdout, workdir)
    if items:
        return Result(items, author, ref.url)
    if res.returncode == 0:
        raise NotFound()
    raise classify(Platform.INSTAGRAM, res.stderr)
