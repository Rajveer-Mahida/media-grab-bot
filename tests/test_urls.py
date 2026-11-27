import httpx
import pytest

from bot.engine.errors import Unsupported
from bot.engine.models import Platform
from bot.engine.urls import classify_url, extract_links, resolve

INSTAGRAM, X = Platform.INSTAGRAM, Platform.X


@pytest.mark.parametrize("url,platform,kind,norm,key", [
    ("https://www.instagram.com/reel/ABC123/?igsh=xyz", INSTAGRAM, "reel", "https://www.instagram.com/reel/ABC123/", "ABC123"),
    ("https://instagram.com/reels/ABC123", INSTAGRAM, "reel", "https://www.instagram.com/reel/ABC123/", "ABC123"),
    ("https://www.instagram.com/p/Cx_-9/?img_index=2", INSTAGRAM, "post", "https://www.instagram.com/p/Cx_-9/", "Cx_-9"),
    ("https://www.instagram.com/some.user/p/Cx9/", INSTAGRAM, "post", "https://www.instagram.com/p/Cx9/", "Cx9"),
    ("https://m.instagram.com/some_user/reel/R1/", INSTAGRAM, "reel", "https://www.instagram.com/reel/R1/", "R1"),
    ("https://www.instagram.com/tv/TV1/", INSTAGRAM, "tv", "https://www.instagram.com/tv/TV1/", "TV1"),
    ("https://www.instagram.com/stories/some.user/3141592653/?utm_source=ig", INSTAGRAM, "story", "https://www.instagram.com/stories/some.user/3141592653/", "some.user/3141592653"),
    ("https://www.instagram.com/stories/some.user/", INSTAGRAM, "story", "https://www.instagram.com/stories/some.user/", "some.user"),
    ("https://www.instagram.com/share/reel/BAbc12/", INSTAGRAM, "short", "https://www.instagram.com/share/reel/BAbc12/", "BAbc12"),
    ("https://instagr.am/p/Cx9/", INSTAGRAM, "short", "https://instagr.am/p/Cx9/", "Cx9"),
    ("https://x.com/someone/status/1790000000000000000?s=46&t=abc", X, "status", "https://x.com/someone/status/1790000000000000000", "1790000000000000000"),
    ("https://twitter.com/someone/status/179/photo/1", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://mobile.twitter.com/someone/status/179", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://www.x.com/someone/status/179", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://fxtwitter.com/someone/status/179", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://vxtwitter.com/someone/status/179", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://fixupx.com/someone/status/179/video/1", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://x.com/i/status/179", X, "status", "https://x.com/i/status/179", "179"),
    ("https://x.com/i/web/status/179", X, "status", "https://x.com/i/status/179", "179"),
    ("https://t.co/AbCdEf", X, "short", "https://t.co/AbCdEf", "AbCdEf"),
])
def test_classify_url(url, platform, kind, norm, key):
    ref = classify_url(url)
    assert ref is not None
    assert (ref.platform, ref.kind, ref.url, ref.key) == (platform, kind, norm, key)


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/some.user/", "https://x.com/someone",
    "https://youtube.com/watch?v=x", "https://www.instagram.com/accounts/login/",
    "https://notinstagram.com/p/X/", "https://t.co/", "ftp://x.com/a/status/1",
])
def test_classify_url_unsupported(url):
    assert classify_url(url) is None


def test_extract_share_menu_text():
    refs = extract_links("Check this out https://www.instagram.com/reel/ABC123/?igsh=xyz).")
    assert [r.url for r in refs] == ["https://www.instagram.com/reel/ABC123/"]


def test_extract_multiple_in_order_dedup():
    t = "a https://x.com/u/status/1 b https://www.instagram.com/p/P1/ c https://twitter.com/u/status/1"
    assert [r.key for r in extract_links(t)] == ["1", "P1"]


def test_extract_none():
    assert extract_links("hello https://example.com") == []


def _client(routes: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        resp = routes.get(str(request.url))
        assert resp is not None, f"unexpected request {request.url}"
        assert "cookie" not in request.headers
        return resp
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_resolve_follows_redirect():
    client = _client({
        "https://www.instagram.com/share/reel/BAbc12/": httpx.Response(302, headers={"Location": "https://www.instagram.com/reel/REAL1/?igsh=q"}),
        "https://www.instagram.com/reel/REAL1/?igsh=q": httpx.Response(200),
    })
    ref = await resolve(classify_url("https://www.instagram.com/share/reel/BAbc12/"), client)
    assert ref.url == "https://www.instagram.com/reel/REAL1/"
    assert ref.kind == "reel"


async def test_resolve_login_redirect_uses_next_param():
    client = _client({
        "https://www.instagram.com/share/reel/BAbc12/": httpx.Response(302, headers={"Location": "https://www.instagram.com/accounts/login/?next=%2Freel%2FREAL1%2F"}),
        "https://www.instagram.com/accounts/login/?next=%2Freel%2FREAL1%2F": httpx.Response(200),
    })
    ref = await resolve(classify_url("https://www.instagram.com/share/reel/BAbc12/"), client)
    assert ref.key == "REAL1"


async def test_resolve_tco_to_x():
    client = _client({
        "https://t.co/AbCdEf": httpx.Response(301, headers={"Location": "https://x.com/u/status/9?s=20"}),
        "https://x.com/u/status/9?s=20": httpx.Response(200),
    })
    ref = await resolve(classify_url("https://t.co/AbCdEf"), client)
    assert (ref.kind, ref.key, ref.platform) == ("status", "9", X)


async def test_resolve_to_unsupported_raises():
    client = _client({
        "https://t.co/AbCdEf": httpx.Response(301, headers={"Location": "https://example.com/"}),
        "https://example.com/": httpx.Response(200),
    })
    with pytest.raises(Unsupported):
        await resolve(classify_url("https://t.co/AbCdEf"), client)


async def test_resolve_network_error_is_failed():
    from bot.engine.errors import Failed

    def handler(request):
        raise httpx.ConnectError("no route")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(Failed):
        await resolve(classify_url("https://t.co/AbCdEf"), client)


async def test_resolve_non_short_is_identity():
    ref = classify_url("https://x.com/u/status/9")
    assert await resolve(ref, _client({})) is ref
