"""X (Twitter) downloads, logged out: yt-dlp for video/GIF, gallery-dl for image tweets."""
from __future__ import annotations

import re
from pathlib import Path

from .errors import DownloadError, NotFound, classify
from .models import LinkRef, Platform, Result
from .proc import ProcRunner, run
from .tools import (
    DOWNLOAD_TIMEOUT, TEXT_TIMEOUT, YTDLP_X_EXTRACTORS, gallery_dl_args, parse_gallery_dl, parse_ytdlp,
    parse_ytdlp_text, read_metadata_value, ytdlp_args, ytdlp_text_args,
)

_AUTHOR_KEYS = [("author", "name"), ("user", "name")]
_TEXT_KEYS = [("content",)]
# yt-dlp found no video in the tweet itself (photo tweet, or only a link to another site)
_NO_VIDEO = ("no video could be found", "unsupported url", "no suitable extractor")
# X appends the tweet's own media link (t.co) to the text
_TRAILING_TCO = re.compile(r"\s*https://t\.co/\w+$")


def _tweet_text(text: str | None) -> str | None:
    text = _TRAILING_TCO.sub("", text or "").strip()
    return text or None


async def _lookup_text(ref: LinkRef, proc_run: ProcRunner) -> str | None:
    """Best effort: a failed lookup only drops the caption text, never the media."""
    try:
        res = await proc_run(ytdlp_text_args(ref.url, YTDLP_X_EXTRACTORS), TEXT_TIMEOUT)
    except DownloadError:
        return None
    return _tweet_text(parse_ytdlp_text(res.stdout)) if res.returncode == 0 else None


async def download_x(ref: LinkRef, workdir: Path, proc_run: ProcRunner = run) -> Result:
    res = await proc_run(ytdlp_args(ref.url, workdir, YTDLP_X_EXTRACTORS), DOWNLOAD_TIMEOUT)
    items, author, text = parse_ytdlp(res.stdout, workdir)
    if items:
        return Result(items, author, ref.url, _tweet_text(text))
    if res.returncode == 0:
        raise NotFound()
    if not any(marker in res.stderr.lower() for marker in _NO_VIDEO):
        raise classify(Platform.X, res.stderr)

    res = await proc_run(gallery_dl_args(ref.url, workdir), DOWNLOAD_TIMEOUT)
    items = parse_gallery_dl(res.stdout, workdir)
    if items:
        # gallery-dl misses the text since X moved it to details.full_text; yt-dlp still reads it
        text = read_metadata_value(workdir, _TEXT_KEYS) or await _lookup_text(ref, proc_run)
        return Result(items, read_metadata_value(workdir, _AUTHOR_KEYS), ref.url, text)
    if res.returncode == 0:
        raise NotFound()
    raise classify(Platform.X, res.stderr)
