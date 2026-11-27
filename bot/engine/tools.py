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
    args += ["-D", str(workdir), "--write-metadata", "-o", "sleep-request=5.0-8.0", url]
    return args


def ytdlp_args(url: str, workdir: Path, cookies: Path | None = None) -> list[str]:
    args = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-progress"]
    if cookies is not None:
        args += ["--cookies", str(cookies)]
    args += [
        "-f", YTDLP_FORMAT,
        "-o", str(workdir / "%(autonumber)03d.%(ext)s"),
        "--print", "after_move:%(uploader_id)s\t%(filepath)s",
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


def parse_ytdlp(stdout: str, workdir: Path) -> tuple[list[MediaItem], str | None]:
    author: str | None = None
    paths: list[str] = []
    for line in stdout.splitlines():
        uploader, sep, path = line.partition("\t")
        if not sep:
            continue
        if author is None and uploader.strip() not in ("", "NA"):
            author = uploader.strip()
        paths.append(path)
    return collect_files(paths, workdir), author


def read_metadata_author(workdir: Path, keys: list[tuple[str, ...]]) -> str | None:
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
            if isinstance(value, str) and value:
                return value
    return None
