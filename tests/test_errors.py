import pytest

from bot.engine.errors import (
    Failed, InstagramPaused, LoginRequired, NoCookies, NotFound, RateLimited,
    TooLarge, XLoginRequired, classify, register_secret, scrub,
)
from bot.engine.models import Platform


def test_scrub_registered_secret():
    register_secret("supersecretvalue")
    assert scrub("cookie supersecretvalue here") == "cookie *** here"


def test_scrub_bot_token_pattern():
    out = scrub("POST https://api.telegram.org/bot123456789:AAHfakefakefakefakefakefakefakefake12/getMe")
    assert "AAH" not in out


def test_scrub_sessionid_forms():
    for s in ["sessionid=abc123%3Axyz", "sessionid\tabc123%3Axyz", '"sessionid": "abc123%3Axyz"']:
        assert "abc123" not in scrub(s), s


def test_scrub_ignores_short_secrets():
    register_secret("ab")
    assert scrub("abc") == "abc"


@pytest.mark.parametrize("stderr,cls", [
    ("ERROR: HTTP Error 429: Too Many Requests", RateLimited),
    ("[instagram][error] Please wait a few minutes before you try again.", RateLimited),
    ("[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)", LoginRequired),
    ("ERROR: checkpoint_required", LoginRequired),
    ("[instagram][error] HTTP Error 404: Not Found", NotFound),
    ("ERROR: Requested content is not available", NotFound),
    ("[instagram][error] something odd", Failed),
])
def test_classify_instagram(stderr, cls):
    assert type(classify(Platform.INSTAGRAM, stderr)) is cls


@pytest.mark.parametrize("stderr,cls", [
    ("ERROR: [twitter] 123: NSFW tweet requires authentication", XLoginRequired),
    ("ERROR: [twitter] 123: Requested tweet is unavailable", NotFound),
    ("ERROR: [twitter] HTTP Error 404", NotFound),
    ("ERROR: weird", Failed),
])
def test_classify_x(stderr, cls):
    assert type(classify(Platform.X, stderr)) is cls


def test_x_429_does_not_raise_ratelimited():
    assert type(classify(Platform.X, "HTTP Error 429")) is Failed


def test_failed_reason_is_last_error_line_scrubbed_and_truncated():
    register_secret("tok-secret-123")
    err = classify(Platform.X, "noise\nERROR: boom tok-secret-123 " + "x" * 500)
    assert err.user_message.startswith("Download failed: ERROR: boom ***")
    assert len(err.user_message) <= len("Download failed: ") + 200


def test_user_messages_exact():
    assert InstagramPaused(125).user_message == "Instagram paused for ~3 more min after rate-limiting; send again later"
    assert TooLarge(73_400_320).user_message == "File is 70 MB — over Telegram's 50 MB limit"
    assert NoCookies().user_message == "No Instagram cookies file — send one with /cookies"
    assert LoginRequired().user_message == "Instagram login expired — refresh cookies"
    assert NotFound().user_message == "Post not found or not visible to your account"
    assert RateLimited().user_message == "Instagram is rate-limiting; try again in a while"
    assert XLoginRequired().user_message == "This tweet needs an X login, which this bot doesn't use"
    assert Failed("x").user_message == "Download failed: x"


def test_nocookies_is_login_required():
    assert isinstance(NoCookies(), LoginRequired)
