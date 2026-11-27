import logging
import os
import stat
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest
from telegram.ext import ApplicationHandlerStop, TypeHandler

from bot.config import Config
from bot.jobs import JobQueue
from bot.telegram_bot import (
    build_application, cmd_hq, cmd_start, gate, handle_cookies_document, handle_text, is_allowed, status_text,
)

VALID = b".instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\t123%3Aabc\n"


@pytest.fixture
def config(tmp_path):
    return Config("123:abc", frozenset({1}), tmp_path / "cookies" / "ig.cookies.txt", tmp_path / "dl")


def make_update(user_id=1, text=None, document=None, caption=None):
    msg = MagicMock()
    msg.text, msg.caption, msg.document = text, caption, document
    msg.message_id = 500
    msg.reply_text = AsyncMock(side_effect=lambda *a, **k: SimpleNamespace(message_id=600 + msg.reply_text.await_count))
    msg.delete = AsyncMock()
    update = MagicMock()
    update.effective_user = SimpleNamespace(id=user_id) if user_id is not None else None
    update.effective_chat = SimpleNamespace(id=99)
    update.effective_message = msg
    return update


def make_context(config, args=None, queue=None):
    return SimpleNamespace(bot=AsyncMock(), args=args or [],
                           bot_data={"config": config, "hq": False, "queue": queue or JobQueue(AsyncMock())})


def make_document(data: bytes, size=None):
    tg_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(data)))
    return SimpleNamespace(file_size=len(data) if size is None else size, get_file=AsyncMock(return_value=tg_file))


def test_is_allowed():
    assert is_allowed(1, frozenset({1}))
    assert not is_allowed(2, frozenset({1}))
    assert not is_allowed(None, frozenset({1}))


async def test_gate_blocks_and_logs(config, caplog):
    update = make_update(user_id=2, text="hi")
    with pytest.raises(ApplicationHandlerStop):
        await gate(update, make_context(config))
    assert "rejected user 2" in caplog.text
    update.effective_message.reply_text.assert_not_awaited()


async def test_gate_allows_owner(config):
    await gate(make_update(user_id=1), make_context(config))


async def test_cookies_valid_writes_deletes_replies(config):
    update = make_update(document=make_document(VALID), caption="/cookies")
    ctx = make_context(config)
    await handle_cookies_document(update, ctx)
    assert config.instagram_cookies.read_bytes() == VALID
    assert stat.S_IMODE(config.instagram_cookies.stat().st_mode) == 0o600
    update.effective_message.delete.assert_awaited_once()
    ctx.bot.send_message.assert_awaited_once_with(chat_id=99, text="cookies updated")


async def test_cookies_invalid_still_deletes(config):
    update = make_update(document=make_document(b"garbage"), caption="/cookies")
    ctx = make_context(config)
    await handle_cookies_document(update, ctx)
    assert not config.instagram_cookies.exists()
    update.effective_message.delete.assert_awaited_once()
    ctx.bot.send_message.assert_awaited_once_with(chat_id=99, text="not a valid Instagram cookies file")


async def test_cookies_oversize_not_downloaded(config):
    doc = make_document(VALID, size=2_000_000)
    update = make_update(document=doc, caption="/cookies")
    ctx = make_context(config)
    await handle_cookies_document(update, ctx)
    doc.get_file.assert_not_awaited()
    update.effective_message.delete.assert_awaited_once()
    assert ctx.bot.send_message.await_args.kwargs["text"] == "not a valid Instagram cookies file"


async def test_cookies_delete_failure_mentions_manual(config):
    update = make_update(document=make_document(VALID), caption="/cookies")
    update.effective_message.delete.side_effect = BadRequest("can't delete")
    ctx = make_context(config)
    await handle_cookies_document(update, ctx)
    assert ctx.bot.send_message.await_args.kwargs["text"] == \
        "cookies updated — couldn't delete your message, delete it manually"


async def test_text_without_links_replies_unsupported(config):
    update = make_update(text="hello there")
    await handle_text(update, make_context(config))
    update.effective_message.reply_text.assert_awaited_once_with("Send an Instagram or X link")


async def test_text_two_links_queues_two_jobs(config):
    queue = JobQueue(AsyncMock())
    update = make_update(text="look https://www.instagram.com/p/A/ and https://x.com/u/status/9")
    await handle_text(update, make_context(config, queue=queue))
    texts = [c.args[0] for c in update.effective_message.reply_text.await_args_list]
    assert texts == ["⏳ Downloading…", "⏳ Queued, 1 ahead"]
    assert queue.pending_count() == 2
    first = queue._queue.get_nowait()
    assert (first.chat_id, first.url, first.status_message_id) == (99, "https://www.instagram.com/p/A/", 601)


async def test_hq_toggle(config):
    ctx = make_context(config, args=["on"])
    update = make_update()
    await cmd_hq(update, ctx)
    assert ctx.bot_data["hq"] is True
    update.effective_message.reply_text.assert_awaited_with("HQ on: images sent as original files")
    ctx.args = ["off"]
    await cmd_hq(update, ctx)
    assert ctx.bot_data["hq"] is False
    ctx.args = ["maybe"]
    await cmd_hq(update, ctx)
    assert "/hq on" in update.effective_message.reply_text.await_args.args[0]


async def test_start_mentions_commands(config):
    update = make_update()
    await cmd_start(update, make_context(config))
    text = update.effective_message.reply_text.await_args.args[0]
    for word in ("Instagram", "X", "/hq", "/status", "/cookies"):
        assert word in text


def test_status_text():
    t = status_text(pending=0, ytdlp="2026.11.23", gallerydl="1.32.21",
                    cookie_age=timedelta(days=3, hours=2), paused_for=0)
    assert "queue: 0" in t and "yt-dlp 2026.11.23" in t and "gallery-dl 1.32.21" in t
    assert "cookies: 3 days old" in t and "paused" not in t
    t2 = status_text(pending=2, ytdlp="a", gallerydl="b", cookie_age=None, paused_for=130)
    assert "cookies: missing" in t2 and "Instagram paused: ~3 min" in t2


def test_build_application_registers_gate_first(config):
    app = build_application(config)
    assert isinstance(app.handlers[-1][0], TypeHandler)
    assert app.bot_data["config"] is config and app.bot_data["hq"] is False


def test_main_exits_2_on_missing_config(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("BOT_TOKEN", "ALLOWED_USER_IDS")}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-m", "bot"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 2
    assert "BOT_TOKEN" in r.stderr
