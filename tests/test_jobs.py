import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest

from bot.config import Config
from bot.engine.errors import NotFound, register_secret
from bot.engine.models import MediaItem, Result
from bot.jobs import Job, JobQueue, log_ref, process_job, wipe_leftovers

URL = "https://www.instagram.com/reel/A/?igsh=1"


@pytest.fixture
def config(tmp_path):
    return Config("1:x", frozenset({1}), tmp_path / "c.txt", tmp_path / "downloads")


def job_dirs(config):
    return list(config.download_dir.glob("job-*")) if config.download_dir.exists() else []


async def _run(job, config, downloader, executor=None, bot=None, hq=False):
    bot = bot or AsyncMock()
    executor = executor or AsyncMock()
    await process_job(job, bot=bot, config=config, pacer=object(), http=object(), hq=lambda: hq,
                      downloader=downloader, executor=executor)
    return bot, executor


def ok_downloader(record=None):
    async def dl(url, workdir, *, cookies, pacer, http):
        if record is not None:
            record.append((url, workdir, cookies))
        p = workdir / "a.jpg"
        p.write_bytes(b"x")
        return Result([MediaItem(p, "image", 1)], "u", "https://www.instagram.com/reel/A/")
    return dl


async def test_submit_reports_jobs_ahead():
    gate = asyncio.Event()

    async def worker(job):
        await gate.wait()

    q = JobQueue(worker)
    task = asyncio.create_task(q.run_forever())
    assert q.submit(Job(1, "a", 1)) == 0
    await asyncio.sleep(0.01)
    assert q.submit(Job(1, "b", 2)) == 1
    assert q.submit(Job(1, "c", 3)) == 2
    assert q.pending_count() == 2
    gate.set()
    await asyncio.sleep(0.01)
    assert q.pending_count() == 0
    task.cancel()


async def test_queue_continues_after_failure(caplog):
    done = []

    async def worker(job):
        if job.url == "bad":
            raise RuntimeError("boom")
        done.append(job.url)

    q = JobQueue(worker)
    task = asyncio.create_task(q.run_forever())
    q.submit(Job(1, "bad", 1))
    q.submit(Job(1, "good", 2))
    await asyncio.sleep(0.05)
    assert done == ["good"]
    assert "boom" in caplog.text
    task.cancel()


async def test_success_deletes_status_and_workdir(config):
    calls = []
    bot, executor = await _run(Job(5, URL, 77), config, ok_downloader(calls))
    bot.edit_message_text.assert_awaited_with(chat_id=5, message_id=77, text="⏳ Downloading…")
    bot.delete_message.assert_awaited_once_with(chat_id=5, message_id=77)
    assert executor.await_count == 1
    url, workdir, cookies = calls[0]
    assert url == URL and workdir.name.startswith("job-") and cookies == config.instagram_cookies
    assert job_dirs(config) == []


async def test_download_error_edits_status_with_user_message(config):
    async def dl(url, workdir, **kw):
        raise NotFound()
    bot, executor = await _run(Job(5, URL, 77), config, dl)
    bot.edit_message_text.assert_awaited_with(chat_id=5, message_id=77,
                                              text="Post not found or not visible to your account")
    assert executor.await_count == 0
    assert job_dirs(config) == []


async def test_unexpected_error_is_scrubbed(config):
    register_secret("verysecretvalue")

    async def dl(url, workdir, **kw):
        raise RuntimeError("boom verysecretvalue")
    bot, _ = await _run(Job(5, URL, 77), config, dl)
    text = bot.edit_message_text.await_args.kwargs["text"]
    assert text.startswith("Download failed: ") and "***" in text and "verysecretvalue" not in text


async def test_send_failure_still_cleans_workdir(config):
    executor = AsyncMock(side_effect=RuntimeError("network down"))
    bot, _ = await _run(Job(5, URL, 77), config, ok_downloader(), executor=executor)
    assert job_dirs(config) == []
    assert bot.edit_message_text.await_args.kwargs["text"].startswith("Download failed")


async def test_status_edit_failure_does_not_break_job(config):
    bot = AsyncMock()
    bot.edit_message_text.side_effect = BadRequest("Message is not modified")
    _, executor = await _run(Job(5, URL, 77), config, ok_downloader(), bot=bot)
    assert executor.await_count == 1


async def test_hq_flag_passed_to_plan(config):
    executor = AsyncMock()
    await _run(Job(5, URL, 77), config, ok_downloader(), executor=executor, hq=True)
    ops = executor.await_args.args[2]
    assert ops[0].method == "document"


async def test_job_outcome_logged(config, caplog):
    caplog.set_level(logging.INFO)
    await _run(Job(5, URL, 77), config, ok_downloader())
    assert "job instagram.com/reel/A outcome=ok" in caplog.text
    assert "igsh" not in caplog.text


def test_log_ref_strips_query():
    assert log_ref("https://www.instagram.com/reel/A/?igsh=1") == "instagram.com/reel/A"
    assert log_ref("https://x.com/u/status/9?s=1") == "x.com/u/status/9"


def test_wipe_leftovers_only_job_dirs(tmp_path):
    (tmp_path / "job-a").mkdir()
    (tmp_path / "job-b").mkdir()
    (tmp_path / "job-b" / "f.mp4").write_bytes(b"x")
    (tmp_path / "keep.txt").write_text("k")
    (tmp_path / "other").mkdir()
    assert wipe_leftovers(tmp_path) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.txt", "other"]


def test_wipe_leftovers_missing_dir(tmp_path):
    assert wipe_leftovers(tmp_path / "nope") == 0
