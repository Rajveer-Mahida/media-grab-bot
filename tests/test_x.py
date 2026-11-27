import sys

import pytest

from bot.engine.errors import Failed, NotFound, XLoginRequired
from bot.engine.urls import classify_url
from bot.engine.x import download_x
from tests.fakes import FakeRun, step

STATUS = classify_url("https://x.com/someone/status/179")
NO_VIDEO = "ERROR: [twitter] 179: No video could be found in this tweet"
NO_TEXT = step(rc=0, stdout="NA\n")  # yt-dlp text lookup for a tweet with no text


@pytest.fixture
def wd(tmp_path):
    d = tmp_path / "job-1"
    d.mkdir()
    return d


async def test_ytdlp_args_no_cookies(wd):
    run = FakeRun(step(["001.mp4"], stdout="someone\t{wd}/001.mp4\n"))
    await download_x(STATUS, wd, proc_run=run)
    a = run.calls[0]
    assert a[:3] == [sys.executable, "-m", "yt_dlp"]
    assert "--ignore-config" in a
    assert not any(x.startswith("--cookies") or "cookies-update" in x for x in a)
    assert "b[filesize<50M]/b[filesize_approx<50M]/bv*[filesize<45M]+ba/b" in a
    assert a[-1] == STATUS.url


async def test_multi_video_tweet(wd):
    run = FakeRun(step(["001.mp4", "002.mp4"], stdout="someone\t{wd}/001.mp4\nsomeone\t{wd}/002.mp4\n"))
    r = await download_x(STATUS, wd, proc_run=run)
    assert [i.path.name for i in r.items] == ["001.mp4", "002.mp4"]
    assert r.author == "someone" and r.source_url == STATUS.url


async def test_image_tweet_uses_gallery_dl_without_cookies(wd):
    run = FakeRun(step(rc=1, stderr=NO_VIDEO),
                  step(["1.jpg", "2.jpg", "3.jpg", "4.jpg"],
                       stdout="{wd}/1.jpg\n{wd}/2.jpg\n{wd}/3.jpg\n{wd}/4.jpg\n",
                       metadata={"author": {"name": "someone"}}), NO_TEXT)
    r = await download_x(STATUS, wd, proc_run=run)
    g = run.calls[1]
    assert g[:3] == [sys.executable, "-m", "gallery_dl"] and "--config-ignore" in g
    assert not any(x.startswith("--cookies") or "cookies-update" in x for x in g)
    assert [i.kind for i in r.items] == ["image"] * 4
    assert r.author == "someone"


async def test_image_tweet_needing_login(wd):
    run = FakeRun(step(rc=1, stderr=NO_VIDEO),
                  step(rc=4, stderr="[twitter][error] AuthRequired: 'authenticated cookies' needed; login required"))
    with pytest.raises(XLoginRequired):
        await download_x(STATUS, wd, proc_run=run)


async def test_login_needed(wd):
    run = FakeRun(step(rc=1, stderr="ERROR: [twitter] 179: NSFW tweet requires authentication"))
    with pytest.raises(XLoginRequired):
        await download_x(STATUS, wd, proc_run=run)
    assert len(run.calls) == 1


async def test_zero_files_is_notfound(wd):
    run = FakeRun(step(rc=0, stdout=""))
    with pytest.raises(NotFound):
        await download_x(STATUS, wd, proc_run=run)


async def test_generic_error_is_failed(wd):
    run = FakeRun(step(rc=1, stderr="ERROR: something broke"))
    with pytest.raises(Failed):
        await download_x(STATUS, wd, proc_run=run)


async def test_ytdlp_restricted_to_twitter_extractors(wd):
    run = FakeRun(step(["001.mp4"], stdout="someone\t{wd}/001.mp4\n"))
    await download_x(STATUS, wd, proc_run=run)
    a = run.calls[0]
    assert a[a.index("--use-extractors") + 1] == "twitter(:.+)?"


async def test_unsupported_url_from_linked_content_falls_back_to_images(wd):
    run = FakeRun(step(rc=1, stderr="ERROR: Unsupported URL: https://news.example/article"),
                  step(["1.jpg"], stdout="{wd}/1.jpg\n"), NO_TEXT)
    r = await download_x(STATUS, wd, proc_run=run)
    assert [i.kind for i in r.items] == ["image"]
    assert run.calls[1][:3][2] == "gallery_dl"


async def test_no_suitable_extractor_falls_back_to_images(wd):
    run = FakeRun(step(rc=1, stderr="ERROR: No suitable extractor found for URL https://youtu.be/x"),
                  step(["1.jpg"], stdout="{wd}/1.jpg\n"), NO_TEXT)
    r = await download_x(STATUS, wd, proc_run=run)
    assert len(r.items) == 1


async def test_x_caption_uses_handle(wd):
    run = FakeRun(step(["001.mp4"], stdout="someone\t{wd}/001.mp4\n"))
    await download_x(STATUS, wd, proc_run=run)
    a = run.calls[0]
    assert a[a.index("--print") + 1] == "after_move:%(uploader_id)s\t%(description)j\t%(filepath)s"


async def test_tweet_text_from_ytdlp(wd):
    run = FakeRun(step(["001.mp4"], stdout='someone\t"Look at this https://t.co/x"\t{wd}/001.mp4\n'))
    # the trailing t.co link is the tweet's own media link
    assert (await download_x(STATUS, wd, proc_run=run)).text == "Look at this"


async def test_tweet_without_text_from_ytdlp(wd):
    run = FakeRun(step(["001.mp4"], stdout="someone\tNA\t{wd}/001.mp4\n"))
    r = await download_x(STATUS, wd, proc_run=run)
    assert r.text is None and len(r.items) == 1


async def test_image_tweet_text_from_gallery_dl_content(wd):
    run = FakeRun(step(rc=1, stderr=NO_VIDEO),
                  step(["1.jpg"], stdout="{wd}/1.jpg\n", metadata={"author": {"name": "someone"}, "content": "pic text"}))
    assert (await download_x(STATUS, wd, proc_run=run)).text == "pic text"
    assert len(run.calls) == 2  # no separate text lookup needed


def photo_tweet_steps(*text_lookup):
    return (step(rc=1, stderr=NO_VIDEO),
            step(["1.jpg"], stdout="{wd}/1.jpg\n", metadata={"author": {"name": "someone"}, "content": ""}),
            *text_lookup)


async def test_photo_tweet_text_looked_up_with_ytdlp_when_gallery_dl_has_none(wd):
    # real-world: X moved tweet text to details.full_text and gallery-dl returns content ""
    run = FakeRun(*photo_tweet_steps(step(rc=0, stdout='"Bas yahi bacha tha wp me https://t.co/HdkzrDB8Co"\n')))
    r = await download_x(STATUS, wd, proc_run=run)
    assert r.text == "Bas yahi bacha tha wp me"
    assert [i.kind for i in r.items] == ["image"] and r.author == "someone"
    t = run.calls[2]
    assert t[:3] == [sys.executable, "-m", "yt_dlp"]
    for flag in ["--ignore-config", "--skip-download", "--ignore-no-formats-error"]:
        assert flag in t
    assert t[t.index("--use-extractors") + 1] == "twitter(:.+)?"
    assert t[t.index("--print") + 1] == "%(description)j"
    assert not any("cookies" in x for x in t)
    assert t[-1] == STATUS.url
    assert run.timeouts[2] == 60


async def test_text_lookup_error_still_sends_media(wd):
    run = FakeRun(*photo_tweet_steps(step(rc=1, stderr="ERROR: [twitter] 179: something broke")))
    r = await download_x(STATUS, wd, proc_run=run)
    assert r.text is None and len(r.items) == 1


async def test_text_lookup_timeout_still_sends_media(wd):
    fake = FakeRun(*photo_tweet_steps())

    async def run(args, timeout):
        if len(fake.calls) == 2:
            raise Failed("timed out after 60s")
        return await fake(args, timeout)

    r = await download_x(STATUS, wd, proc_run=run)
    assert r.text is None and len(r.items) == 1


@pytest.mark.parametrize("printed, text", [
    ('"https://t.co/HdkzrDB8Co"', None),
    ('"see https://t.co/a then https://t.co/b"', "see https://t.co/a then"),
    ('"line one\\nline two"', "line one\nline two"),
])
async def test_trailing_media_link_stripped(wd, printed, text):
    run = FakeRun(*photo_tweet_steps(step(rc=0, stdout=printed + "\n")))
    assert (await download_x(STATUS, wd, proc_run=run)).text == text
