"""Find, classify and normalize Instagram / X links."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from .errors import Failed, Unsupported
from .models import LinkRef, Platform

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING = ").,!?;:'\"]"

_IG_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
_IG_SHORT_HOSTS = {"instagr.am", "www.instagr.am"}
_X_HOSTS = {
    "x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com",
    "fxtwitter.com", "www.fxtwitter.com", "vxtwitter.com", "www.vxtwitter.com",
    "fixupx.com", "fixvx.com",
}
_X_SHORT_HOSTS = {"t.co"}

_IG_SHARE = re.compile(r"^/share/(?:[\w-]+/)*([\w-]+)/?$")
_IG_POST = re.compile(r"^/(?:[\w.]+/)?(p|reel|reels|tv)/([\w-]+)(?:/.*)?$")
_IG_STORY = re.compile(r"^/stories/([\w.]+)/(?:(\d+)/?)?$")
_X_STATUS = re.compile(r"^/(i/web|i|\w+)/status/(\d+)(?:/.*)?$")
_SHORT_PATH = re.compile(r"^/(?:[\w-]+/)*([\w-]+)/?$")

_IG_KIND = {"p": "post", "reel": "reel", "reels": "reel", "tv": "tv"}
_IG_BASE = "https://www.instagram.com"
_MAX_HOPS = 5
_FETCHABLE_HOSTS = _IG_HOSTS | _IG_SHORT_HOSTS | _X_HOSTS | _X_SHORT_HOSTS


def classify_url(url: str) -> LinkRef | None:
    """Return a normalized LinkRef for a supported URL, else None."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    path = parts.path or "/"

    if host in _IG_HOSTS:
        if m := _IG_SHARE.match(path):
            return LinkRef(Platform.INSTAGRAM, "short", f"{_IG_BASE}{path}", m.group(1))
        if m := _IG_STORY.match(path):
            user, story_id = m.group(1), m.group(2)
            if story_id:
                return LinkRef(Platform.INSTAGRAM, "story", f"{_IG_BASE}/stories/{user}/{story_id}/",
                               f"{user}/{story_id}")
            return LinkRef(Platform.INSTAGRAM, "story", f"{_IG_BASE}/stories/{user}/", user)
        if m := _IG_POST.match(path):
            kind = _IG_KIND[m.group(1)]
            segment = "reel" if kind == "reel" else m.group(1)
            code = m.group(2)
            return LinkRef(Platform.INSTAGRAM, kind, f"{_IG_BASE}/{segment}/{code}/", code)
        return None

    if host in _IG_SHORT_HOSTS:
        if m := _SHORT_PATH.match(path):
            return LinkRef(Platform.INSTAGRAM, "short", f"https://{host}{path}", m.group(1))
        return None

    if host in _X_HOSTS:
        if m := _X_STATUS.match(path):
            user, status_id = m.group(1), m.group(2)
            user = "i" if user in ("i", "i/web") else user
            return LinkRef(Platform.X, "status", f"https://x.com/{user}/status/{status_id}", status_id)
        return None

    if host in _X_SHORT_HOSTS:
        if m := _SHORT_PATH.match(path):
            return LinkRef(Platform.X, "short", f"https://t.co{path}", m.group(1))
        return None

    return None


def extract_links(text: str) -> list[LinkRef]:
    """All supported links in `text`, in order, without duplicates."""
    seen: set[str] = set()
    refs: list[LinkRef] = []
    for match in _URL_RE.finditer(text):
        ref = classify_url(match.group(0).rstrip(_TRAILING))
        if ref and ref.url not in seen:
            seen.add(ref.url)
            refs.append(ref)
    return refs


def _from_hop(url: str) -> LinkRef | None:
    """Classify a redirect hop; Instagram login pages carry the target in ?next=."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() in _IG_HOSTS and parts.path.startswith("/accounts/login"):
        nxt = parse_qs(parts.query).get("next", [""])[0]
        if nxt.startswith("/"):
            return classify_url(_IG_BASE + nxt)
        return None
    return classify_url(url)


async def resolve(ref: LinkRef, http: httpx.AsyncClient) -> LinkRef:
    """Follow redirects of a share/short link until it becomes a supported link."""
    if ref.kind != "short":
        return ref
    url = ref.url
    try:
        for _ in range(_MAX_HOPS + 1):
            if (urlsplit(url).hostname or "").lower() not in _FETCHABLE_HOSTS:
                raise Unsupported()  # never contact sites other than Instagram / X
            resp = await http.get(url, follow_redirects=False, timeout=15)
            if not resp.is_redirect:
                break
            url = urljoin(url, resp.headers["location"])
            hop = _from_hop(url)
            if hop and hop.kind != "short":
                return hop
    except httpx.HTTPError as exc:
        raise Failed(f"couldn't open short link ({type(exc).__name__})") from None
    finally:
        http.cookies.clear()
    hop = _from_hop(url)
    if hop and hop.kind != "short":
        return hop
    raise Unsupported()
