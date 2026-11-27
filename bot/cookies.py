"""Instagram cookies.txt: validation, safe storage and age."""
from __future__ import annotations

import os
import tempfile
import time
from datetime import timedelta
from pathlib import Path

MAX_COOKIE_FILE_BYTES = 1_000_000
_HTTPONLY = "#HttpOnly_"


def validate_cookies(data: bytes) -> bool:
    """True if `data` is a Netscape cookies file with a non-empty instagram.com sessionid."""
    if not data or len(data) > MAX_COOKIE_FILE_BYTES:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    for raw in text.splitlines():
        line = raw.strip("\r")
        if line.startswith(_HTTPONLY):
            line = line[len(_HTTPONLY):]
        elif line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, name, value = fields[0].lower().lstrip("."), fields[5], fields[6].strip()
        if (domain == "instagram.com" or domain.endswith(".instagram.com")) and name == "sessionid" and value:
            return True
    return False


def write_cookies_atomic(path: Path, data: bytes) -> None:
    """Write `data` to `path` with mode 0600 via a temp file + rename."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cookies-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cookie_age(path: Path) -> timedelta | None:
    try:
        return timedelta(seconds=max(0.0, time.time() - path.stat().st_mtime))
    except OSError:
        return None
