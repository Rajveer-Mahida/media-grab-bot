"""Instagram downloads via gallery-dl, with yt-dlp as fallback for reels/IGTV."""
from __future__ import annotations

from pathlib import Path

from .errors import Failed, LoginRequired, NotFound, classify
from .models import LinkRef, Platform, Result
from .proc import ProcRunner, run
from .tools import (
    DOWNLOAD_TIMEOUT, YTDLP_INSTAGRAM_EXTRACTORS, gallery_dl_args, parse_gallery_dl, parse_ytdlp, read_metadata_value, ytdlp_args,
)

_AUTHOR_KEYS = [("username",), ("owner_username",)]
_TEXT_KEYS = [("description",)]
_YTDLP_KINDS = ("reel", "tv", "post")


async def download_instagram(ref: LinkRef, workdir: Path, cookies: Path | None,
                             proc_run: ProcRunner = run) -> Result:
    res = await proc_run(gallery_dl_args(ref.url, workdir, cookies), DOWNLOAD_TIMEOUT)
    items = parse_gallery_dl(res.stdout, workdir)
    if items:
        return Result(items, read_metadata_value(workdir, _AUTHOR_KEYS), ref.url,
                      read_metadata_value(workdir, _TEXT_KEYS))
    if res.returncode == 0:
        raise NotFound()
    err = classify(Platform.INSTAGRAM, res.stderr)
    # Logged out, gallery-dl often gets 401 where yt-dlp still works for public videos.
    if not (isinstance(err, (Failed, LoginRequired)) and ref.kind in _YTDLP_KINDS):
        raise err

    # Instagram's uploader_id is a numeric id; channel holds the @username
    args = ytdlp_args(ref.url, workdir, YTDLP_INSTAGRAM_EXTRACTORS, cookies, author_field="channel,uploader_id")
    res = await proc_run(args, DOWNLOAD_TIMEOUT)
    items, author, text = parse_ytdlp(res.stdout, workdir)
    if items:
        return Result(items, author, ref.url, text)
    if res.returncode == 0:
        raise NotFound()
    raise classify(Platform.INSTAGRAM, res.stderr)
