from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from telegram import InputMediaDocument, InputMediaPhoto, InputMediaVideo

from bot.engine.media import PHOTO_MAX_BYTES
from bot.engine.models import MediaItem, Result
from bot.sender import SendGroup, SendSingle, caption_for, execute, plan_sends

CAP = "@u\nhttps://x"


def mk(kind, n=0, size=100):
    ext = {"video": "mp4", "gif": "mp4", "image": "jpg"}[kind]
    return MediaItem(path=Path(f"/w/{kind}{n}.{ext}"), kind=kind, size=size, width=10, height=20, duration=3.7)


def R(items, author="u"):
    return Result(items, author, "https://x")


def test_caption():
    assert caption_for(R([])) == CAP
    assert caption_for(R([], author=None)) == "https://x"


def test_single_video():
    v = mk("video")
    assert plan_sends(R([v]), hq=False) == [SendSingle("video", v, CAP)]


def test_single_gif():
    g = mk("gif")
    assert plan_sends(R([g]), hq=False) == [SendSingle("animation", g, CAP)]


def test_single_image_is_photo():
    i = mk("image")
    assert plan_sends(R([i]), hq=False) == [SendSingle("photo", i, CAP)]


def test_single_big_image_is_document():
    i = mk("image", size=PHOTO_MAX_BYTES + 1)
    assert plan_sends(R([i]), hq=False) == [SendSingle("document", i, CAP)]


def test_hq_single_image_is_document():
    i = mk("image")
    assert plan_sends(R([i]), hq=True) == [SendSingle("document", i, CAP)]


def test_hq_does_not_affect_video():
    v = mk("video")
    assert plan_sends(R([v]), hq=True) == [SendSingle("video", v, CAP)]


def test_carousel_12_items_chunks_10_and_2():
    items = [mk("image", n) for n in range(12)]
    assert plan_sends(R(items), hq=False) == [SendGroup("visual", items[:10], CAP), SendGroup("visual", items[10:], None)]


def test_carousel_11_items_leftover_single():
    items = [mk("image", n) for n in range(11)]
    assert plan_sends(R(items), hq=False) == [SendGroup("visual", items[:10], CAP), SendSingle("photo", items[10], None)]


def test_hq_mixed_splits_documents_from_videos():
    i0, i1, v0, v1 = mk("image", 0), mk("image", 1), mk("video", 0), mk("video", 1)
    assert plan_sends(R([i0, v0, i1, v1]), hq=True) == [
        SendGroup("visual", [v0, v1], CAP), SendGroup("document", [i0, i1], None)]


def test_big_image_in_carousel_goes_to_documents():
    i0, big, v0 = mk("image", 0), mk("image", 1, PHOTO_MAX_BYTES + 1), mk("video", 0)
    assert plan_sends(R([i0, big, v0]), hq=False) == [
        SendGroup("visual", [i0, v0], CAP), SendSingle("document", big, None)]


def test_gif_never_in_group():
    i0, i1, g = mk("image", 0), mk("image", 1), mk("gif")
    assert plan_sends(R([i0, g, i1]), hq=False) == [SendGroup("visual", [i0, i1], CAP), SendSingle("animation", g, None)]


def test_empty_result_plans_nothing():
    assert plan_sends(R([]), hq=False) == []


@pytest.fixture
def files(tmp_path):
    def _f(kind, n=0):
        item = mk(kind, n)
        item.path = tmp_path / item.path.name
        item.path.write_bytes(b"data")
        return item
    return _f


async def test_execute_single_video(files):
    bot = AsyncMock()
    v = files("video")
    await execute(bot, 42, [SendSingle("video", v, CAP)])
    kw = bot.send_video.await_args.kwargs
    assert kw["chat_id"] == 42 and kw["caption"] == CAP and kw["supports_streaming"] is True
    assert (kw["width"], kw["height"], kw["duration"]) == (10, 20, 4)


async def test_execute_animation_and_photo_and_document(files):
    bot = AsyncMock()
    await execute(bot, 1, [SendSingle("animation", files("gif"), None), SendSingle("photo", files("image"), CAP),
                           SendSingle("document", files("image", 1), None)])
    assert bot.send_animation.await_count == 1
    assert bot.send_photo.await_args.kwargs["caption"] == CAP
    assert bot.send_document.await_count == 1


async def test_execute_group(files):
    bot = AsyncMock()
    i, v = files("image"), files("video")
    await execute(bot, 7, [SendGroup("visual", [i, v], CAP)])
    media = bot.send_media_group.await_args.kwargs["media"]
    assert isinstance(media[0], InputMediaPhoto) and isinstance(media[1], InputMediaVideo)
    assert media[0].caption == CAP and media[1].caption is None
    assert media[1].supports_streaming is True


async def test_execute_document_group(files):
    bot = AsyncMock()
    await execute(bot, 7, [SendGroup("document", [files("image"), files("image", 1)], None)])
    media = bot.send_media_group.await_args.kwargs["media"]
    assert all(isinstance(m, InputMediaDocument) for m in media)
