"""X (Twitter) downloads, logged out: yt-dlp for video/GIF, gallery-dl for image tweets."""
from __future__ import annotations

from pathlib import Path

from .errors import NotFound, classify
from .models import LinkRef, Platform, Result
from .proc import ProcRunner, run
from .tools import DOWNLOAD_TIMEOUT, gallery_dl_args, parse_gallery_dl, parse_ytdlp, read_metadata_author, ytdlp_args

_AUTHOR_KEYS = [("author", "name"), ("user", "name")]


async def download_x(ref: LinkRef, workdir: Path, proc_run: ProcRunner = run) -> Result:
    res = await proc_run(ytdlp_args(ref.url, workdir), DOWNLOAD_TIMEOUT)
    items, author = parse_ytdlp(res.stdout, workdir)
    if items:
        return Result(items, author, ref.url)
    if res.returncode == 0:
        raise NotFound()
    if "no video could be found" not in res.stderr.lower():
        raise classify(Platform.X, res.stderr)

    res = await proc_run(gallery_dl_args(ref.url, workdir), DOWNLOAD_TIMEOUT)
    items = parse_gallery_dl(res.stdout, workdir)
    if items:
        return Result(items, read_metadata_author(workdir, _AUTHOR_KEYS), ref.url)
    if res.returncode == 0:
        raise NotFound()
    raise classify(Platform.X, res.stderr)
