"""Typed download errors, error classification and secret scrubbing."""
from __future__ import annotations

import math
import re

from .models import Platform

_SECRETS: set[str] = set()
_MIN_SECRET_LEN = 4
_REASON_MAX = 200

_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")
_COOKIE_RE = re.compile(
    r"(sessionid|csrftoken|ds_user_id|mid|ig_did)([\"']?\s*[:=\t]\s*[\"']?)[^\s;\"']+"
)


def register_secret(value: str) -> None:
    """Remember a value that must never appear in logs or chat."""
    if value and len(value) >= _MIN_SECRET_LEN:
        _SECRETS.add(value)


def scrub(text: str) -> str:
    """Replace registered secrets, bot tokens and auth cookie values with ***."""
    for secret in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(secret, "***")
    text = _TOKEN_RE.sub("***", text)
    return _COOKIE_RE.sub(r"\1\2***", text)


class DownloadError(Exception):
    message = "Download failed"

    @property
    def user_message(self) -> str:
        return self.message


class LoginRequired(DownloadError):
    message = "Instagram login expired — refresh cookies"


class NoCookies(LoginRequired):
    message = ("This needs an Instagram login (private account, story, or blocked logged out) "
               "— send your cookies.txt to the bot")


class NotFound(DownloadError):
    message = "Post not found or not visible to your account"


class RateLimited(DownloadError):
    message = "Instagram is rate-limiting; try again in a while"


class XLoginRequired(DownloadError):
    message = "This tweet needs an X login, which this bot doesn't use"


class Unsupported(DownloadError):
    message = "Send an Instagram or X link"


class InstagramPaused(DownloadError):
    def __init__(self, seconds: float):
        super().__init__(seconds)
        self.seconds = seconds

    @property
    def user_message(self) -> str:
        minutes = math.ceil(self.seconds / 60)
        return f"Instagram paused for ~{minutes} more min after rate-limiting; send again later"


class TooLarge(DownloadError):
    def __init__(self, size_bytes: int):
        super().__init__(size_bytes)
        self.size_bytes = size_bytes

    @property
    def user_message(self) -> str:
        mb = round(self.size_bytes / (1024 * 1024))
        return f"File is {mb} MB — over Telegram's 50 MB limit"


class Failed(DownloadError):
    def __init__(self, reason: str):
        reason = scrub(reason)[:_REASON_MAX]
        super().__init__(reason)
        self.reason = reason

    @property
    def user_message(self) -> str:
        return f"Download failed: {self.reason}"


_URL_RE = re.compile(r"https?://[^\s'\"]+")
_IG_RULES: list[tuple[type[DownloadError], re.Pattern[str]]] = [
    (RateLimited, re.compile(r"\b429\b|too many requests|please wait a few minutes")),
    (LoginRequired, re.compile(r"login|checkpoint_required|\b401\b")),
    (NotFound, re.compile(r"\b404\b|not found|not available|private")),
]
_X_RULES: list[tuple[type[DownloadError], re.Pattern[str]]] = [
    (XLoginRequired, re.compile(r"requires authentication|nsfw|log ?in|age-restricted|not authorized")),
    (NotFound, re.compile(r"\b404\b|tweet is unavailable|tweet unavailable|not found|no status found")),
]


def _reason(stderr: str) -> str:
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    if not lines:
        return "unknown error"
    errs = [ln for ln in lines if "error" in ln.lower()]
    return (errs or lines)[-1]


def classify(platform: Platform, stderr: str) -> DownloadError:
    """Map downloader stderr to the most specific DownloadError."""
    low = _URL_RE.sub(" ", stderr).lower()
    rules = _IG_RULES if platform is Platform.INSTAGRAM else _X_RULES
    for cls, pattern in rules:
        if pattern.search(low):
            return cls()
    return Failed(_reason(stderr))
