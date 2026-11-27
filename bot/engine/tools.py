"""Command lines for gallery-dl / yt-dlp and parsing their output."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .media import kind_for_path
from .models import MediaItem

DOWNLOAD_TIMEOUT = 300
YTDLP_FORMAT = "b[filesize<50M]/b[filesize_approx<50M]/bv*[filesize<45M]+ba/b"


def gallery_dl_args(url: str, workdir: Path, cookies: Path | None = None) -> list[str]:
    args = [sys.executable, "-m", "gallery_dl", "--config-ignore", "--no-input"]
    if cookies is not None:
        args += ["--cookies", str(cookies), "-o", "cookies-update=false"]
    # sleep-429=0 + retries=1: fail fast on rate limiting instead of retrying for minutes
    args += ["-D", str(workdir), "--write-metadata", "-o", "sleep-request=5.0-8.0",
             "-o", "sleep-429=0", "-o", "retries=1", url]
    return args


YTDLP_X_EXTRACTORS = "twitter(:.+)?"
YTDLP_INSTAGRAM_EXTRACTORS = "instagram(:.+)?"


def ytdlp_args(url: str, workdir: Path, extractors: str, cookies: Path | None = None,
               author_field: str = "uploader_id") -> list[str]:
    """`extractors` limits yt-dlp to one site, so links inside a post are never followed.
    `author_field` is the yt-dlp field (with fallbacks) used for the caption's @handle."""
    args = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-progress", "--use-extractors", extractors]
    if cookies is not None:
        args += ["--cookies", str(cookies)]
    args += [
        "-f", YTDLP_FORMAT,
        "-o", str(workdir / "%(autonumber)03d.%(ext)s"),
        "--print", f"after_move:%({author_field})s\t%(description)j\t%(filepath)s",
        "--no-simulate", "--merge-output-format", "mp4", url,
    ]
    return args


def _media_item(path: Path) -> MediaItem | None:
    kind = kind_for_path(path)
    if kind is None or not path.is_file():
        return None
    return MediaItem(path=path, kind=kind, size=path.stat().st_size)


def collect_files(lines: list[str], workdir: Path) -> list[MediaItem]:
    """Media files named in `lines` that really exist inside `workdir`, in order."""
    root = workdir.resolve()
    seen: set[Path] = set()
    items: list[MediaItem] = []
    for line in lines:
        line = line.strip()
        if line.startswith("# "):
            line = line[2:]
        if not line:
            continue
        path = Path(line).resolve()
        if path in seen or not path.is_relative_to(root):
            continue
        item = _media_item(path)
        if item:
            seen.add(path)
            items.append(item)
    return items


def parse_gallery_dl(stdout: str, workdir: Path) -> list[MediaItem]:
    return collect_files(stdout.splitlines(), workdir)


def _clean_text(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _decode_description(field: str) -> str | None:
    """yt-dlp prints the description JSON-encoded (%(description)j) so it stays on one line."""
    try:
        return _clean_text(json.loads(field))
    except ValueError:
        return None


def parse_ytdlp(stdout: str, workdir: Path) -> tuple[list[MediaItem], str | None, str | None]:
    """Parse `author<TAB>description-json<TAB>path` lines into (items, author, text)."""
    author: str | None = None
    text: str | None = None
    paths: list[str] = []
    for line in stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        uploader, path = fields[0].strip(), fields[-1]
        if author is None and uploader not in ("", "NA"):
            author = uploader
        if text is None and len(fields) >= 3:
            text = _decode_description(fields[1])
        paths.append(path)
    return collect_files(paths, workdir), author, text


def read_metadata_value(workdir: Path, keys: list[tuple[str, ...]]) -> str | None:
    """First non-empty value at any of the key paths, from gallery-dl metadata JSON files."""
    for meta in sorted(workdir.glob("*.json")):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key_path in keys:
            value = data
            for key in key_path:
                value = value.get(key) if isinstance(value, dict) else None
            if _clean_text(value):
                return _clean_text(value)
    return None
