import os
import stat
import time
from datetime import timedelta

import pytest

from bot.cookies import MAX_COOKIE_FILE_BYTES, cookie_age, validate_cookies, write_cookies_atomic

VALID = b"# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\t123%3Aabc\n"


def test_max_size():
    assert MAX_COOKIE_FILE_BYTES == 1_000_000


def test_valid():
    assert validate_cookies(VALID)


def test_valid_without_header():
    assert validate_cookies(VALID.split(b"\n", 1)[1])


def test_valid_crlf_and_httponly_prefix():
    data = b"#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\t123%3Aabc\r\n"
    assert validate_cookies(data)


@pytest.mark.parametrize("data", [
    b"", b"\xff\xfe", b"hello",
    VALID.replace(b"sessionid", b"csrftoken"),
    VALID.replace(b".instagram.com", b".x.com"),
    VALID.replace(b".instagram.com", b".evilinstagram.com"),
    VALID.replace(b"123%3Aabc", b""),
    b"a" * 1_000_001,
])
def test_invalid(data):
    assert not validate_cookies(data)


def test_write_atomic_sets_600(tmp_path):
    p = tmp_path / "cookies" / "ig.txt"
    write_cookies_atomic(p, VALID)
    assert p.read_bytes() == VALID
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    assert list(p.parent.iterdir()) == [p]


def test_write_atomic_replaces_existing(tmp_path):
    p = tmp_path / "ig.txt"
    p.write_bytes(b"old")
    write_cookies_atomic(p, VALID)
    assert p.read_bytes() == VALID


def test_cookie_age_missing(tmp_path):
    assert cookie_age(tmp_path / "nope") is None


def test_cookie_age(tmp_path):
    p = tmp_path / "ig.txt"
    p.write_bytes(VALID)
    three_days_ago = time.time() - 3 * 86400
    os.utime(p, (three_days_ago, three_days_ago))
    age = cookie_age(p)
    assert timedelta(days=2, hours=23) < age < timedelta(days=3, hours=1)
