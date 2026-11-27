import sys

import pytest

from bot.engine.errors import Failed, LoginRequired, NotFound, RateLimited
from bot.engine.instagram import download_instagram
from bot.engine.urls import classify_url
from tests.fakes import FakeRun, step

POST = classify_url("https://www.instagram.com/p/Cx9/")
REEL = classify_url("https://www.instagram.com/reel/R1/")


@pytest.fixture
def cookies(tmp_path):
    p = tmp_path / "ig.cookies.txt"
    p.write_text("cookie")
    return p


@pytest.fixture
def wd(tmp_path):
    d = tmp_path / "job-1"
    d.mkdir()
    return d


async def test_args_contain_safety_flags(wd, cookies):
    run = FakeRun(step(["1.jpg"], stdout="{wd}/1.jpg\n"))
    await download_instagram(POST, wd, cookies, proc_run=run)
    a = run.calls[0]
    assert a[:3] == [sys.executable, "-m", "gallery_dl"]
    for flag in ["--config-ignore", "--write-metadata", "--no-input"]:
        assert flag in a
    assert a[a.index("--cookies") + 1] == str(cookies)
    assert a[a.index("-D") + 1] == str(wd)
    assert "sleep-request=5.0-8.0" in a and "cookies-update=false" in a
    assert a[-1] == POST.url
    assert run.timeouts == [300]


async def test_anonymous_run_has_no_cookie_flags(wd):
    run = FakeRun(step(rc=1, stderr="something odd"), step(["001.mp4"], stdout="u\t{wd}/001.mp4\n"))
    await download_instagram(REEL, wd, None, proc_run=run)
    for call in run.calls:
        assert "--cookies" not in call and "cookies-update=false" not in call


async def test_carousel_order_and_author(wd, cookies):
    run = FakeRun(step(["1.jpg", "2.mp4", "3.jpg"],
                       stdout="{wd}/1.jpg\n{wd}/2.mp4\n# {wd}/3.jpg\n",
                       metadata={"username": "some.user"}))
    r = await download_instagram(POST, wd, cookies, proc_run=run)
    assert [i.kind for i in r.items] == ["image", "video", "image"]
    assert [i.path.name for i in r.items] == ["1.jpg", "2.mp4", "3.jpg"]
    assert r.author == "some.user"
    assert r.source_url == POST.url
    assert all(i.size == 10 for i in r.items)


async def test_author_fallback_owner_username(wd, cookies):
    run = FakeRun(step(["1.jpg"], stdout="{wd}/1.jpg\n", metadata={"owner_username": "own"}))
    assert (await download_instagram(POST, wd, cookies, proc_run=run)).author == "own"


async def test_paths_outside_workdir_ignored(wd, cookies, tmp_path):
    (tmp_path / "evil.jpg").write_bytes(b"x")
    run = FakeRun(step(["1.jpg"], stdout=f"{tmp_path}/evil.jpg\n{{wd}}/1.jpg\n"))
    r = await download_instagram(POST, wd, cookies, proc_run=run)
    assert [i.path.name for i in r.items] == ["1.jpg"]


async def test_zero_files_is_notfound(wd, cookies):
    run = FakeRun(step(rc=0, stdout=""))
    with pytest.raises(NotFound):
        await download_instagram(POST, wd, cookies, proc_run=run)


async def test_story_login_error_is_classified(wd, cookies):
    run = FakeRun(step(rc=1, stderr="[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)"))
    with pytest.raises(LoginRequired):
        await download_instagram(classify_url("https://www.instagram.com/stories/u/"), wd, cookies, proc_run=run)


async def test_ratelimit_is_classified(wd, cookies):
    run = FakeRun(step(rc=4, stderr="[instagram][error] HTTP Error 429 Too Many Requests"))
    with pytest.raises(RateLimited):
        await download_instagram(REEL, wd, cookies, proc_run=run)
    assert len(run.calls) == 1


async def test_reel_falls_back_to_ytdlp_on_generic_failure(wd, cookies):
    run = FakeRun(step(rc=1, stderr="[instagram][error] something odd"),
                  step(["001.mp4"], stdout="some.user\t{wd}/001.mp4\n"))
    r = await download_instagram(REEL, wd, cookies, proc_run=run)
    y = run.calls[1]
    assert y[:3] == [sys.executable, "-m", "yt_dlp"]
    assert "--ignore-config" in y and y[y.index("--cookies") + 1] == str(cookies)
    assert [i.kind for i in r.items] == ["video"] and r.author == "some.user"


async def test_story_does_not_fall_back(wd, cookies):
    story = classify_url("https://www.instagram.com/stories/some.user/")
    run = FakeRun(step(rc=1, stderr="[instagram][error] something odd"))
    with pytest.raises(Failed):
        await download_instagram(story, wd, cookies, proc_run=run)
    assert len(run.calls) == 1


async def test_no_fallback_on_not_found(wd, cookies):
    run = FakeRun(step(rc=1, stderr="[instagram][error] HTTP Error 404: Not Found"))
    with pytest.raises(NotFound):
        await download_instagram(REEL, wd, cookies, proc_run=run)
    assert len(run.calls) == 1


async def test_fallback_failure_reports_ytdlp_error(wd, cookies):
    run = FakeRun(step(rc=1, stderr="something odd"),
                  step(rc=1, stderr="ERROR: [Instagram] R1: Requested content is not available"))
    with pytest.raises(NotFound):
        await download_instagram(REEL, wd, cookies, proc_run=run)


async def test_gallery_dl_fails_fast_on_429(wd, cookies):
    run = FakeRun(step(["1.jpg"], stdout="{wd}/1.jpg\n"))
    await download_instagram(POST, wd, cookies, proc_run=run)
    a = run.calls[0]
    assert "sleep-429=0" in a and "retries=1" in a


async def test_ytdlp_fallback_restricted_to_instagram_extractors(wd, cookies):
    run = FakeRun(step(rc=1, stderr="something odd"), step(["001.mp4"], stdout="u\t{wd}/001.mp4\n"))
    await download_instagram(REEL, wd, cookies, proc_run=run)
    y = run.calls[1]
    assert y[y.index("--use-extractors") + 1] == "instagram(:.+)?"


GALLERY_401 = "[instagram][error] HttpError: '401 Unauthorized' for 'https://www.instagram.com/api/v1/media/3910068754956221925/info/'"


@pytest.mark.parametrize("ref", [REEL, POST])
async def test_login_error_falls_back_to_ytdlp(wd, ref):
    # real-world: logged out, gallery-dl gets 401 but yt-dlp can still fetch public reels
    run = FakeRun(step(rc=4, stderr=GALLERY_401), step(["001.mp4"], stdout="u\t{wd}/001.mp4\n"))
    r = await download_instagram(ref, wd, None, proc_run=run)
    assert [i.kind for i in r.items] == ["video"]
    assert run.calls[1][2] == "yt_dlp"


async def test_login_error_on_both_tools_is_login_required(wd):
    run = FakeRun(step(rc=4, stderr=GALLERY_401),
                  step(rc=1, stderr="ERROR: [Instagram] X: Requested content is not available, rate-limit reached or login required"))
    with pytest.raises(LoginRequired):
        await download_instagram(REEL, wd, None, proc_run=run)
