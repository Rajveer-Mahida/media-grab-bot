"""Data types shared by the download engine and its callers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

LinkKind = Literal["post", "reel", "tv", "story", "status", "short"]
MediaKind = Literal["video", "image", "gif"]


class Platform(Enum):
    INSTAGRAM = "instagram"
    X = "x"


@dataclass(frozen=True)
class LinkRef:
    """A supported link, normalized. `key` identifies the post (for logs)."""

    platform: Platform
    kind: LinkKind
    url: str
    key: str


@dataclass
class MediaItem:
    path: Path
    kind: MediaKind
    size: int
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    has_audio: bool = True


@dataclass
class Result:
    items: list[MediaItem]
    author: str | None
    source_url: str
