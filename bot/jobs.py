"""One-at-a-time job queue and the lifecycle of a single download job."""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from telegram.error import TelegramError

from .config import Config
from .engine import download
from .engine.errors import DownloadError, Failed, scrub
from .sender import execute, plan_sends

log = logging.getLogger(__name__)

DOWNLOADING = "⏳ Downloading…"


@dataclass
class Job:
    chat_id: int
    url: str
    status_message_id: int


class JobQueue:
    def __init__(self, worker: Callable[[Job], Awaitable[None]]):
        self._worker = worker
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._busy = False

    def submit(self, job: Job) -> int:
        """Queue `job`; return how many jobs are ahead of it."""
        ahead = self._queue.qsize() + (1 if self._busy else 0)
        self._queue.put_nowait(job)
        return ahead

    def pending_count(self) -> int:
        return self._queue.qsize()

    async def run_forever(self) -> None:
        while True:
            job = await self._queue.get()
            self._busy = True
            try:
                await self._worker(job)
            except Exception:
                log.exception("worker crashed on job %s", log_ref(job.url))
            finally:
                self._busy = False
                self._queue.task_done()


def log_ref(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def wipe_leftovers(download_dir: Path) -> int:
    if not download_dir.is_dir():
        return 0
    removed = 0
    for path in download_dir.glob("job-*"):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


async def _status(bot, job: Job, text: str) -> None:
    try:
        await bot.edit_message_text(chat_id=job.chat_id, message_id=job.status_message_id, text=text)
    except TelegramError as exc:
        log.warning("couldn't update status message: %s", exc)


async def process_job(job: Job, *, bot, config: Config, pacer, http, hq: Callable[[], bool],
                      downloader=download, executor=execute) -> None:
    started = time.monotonic()
    outcome = "ok"
    await _status(bot, job, DOWNLOADING)
    config.download_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="job-", dir=config.download_dir))
    try:
        result = await downloader(job.url, workdir, cookies=config.instagram_cookies, pacer=pacer, http=http)
        await executor(bot, job.chat_id, plan_sends(result, hq()))
        try:
            await bot.delete_message(chat_id=job.chat_id, message_id=job.status_message_id)
        except TelegramError as exc:
            log.warning("couldn't delete status message: %s", exc)
    except DownloadError as err:
        outcome = type(err).__name__
        await _status(bot, job, err.user_message)
    except Exception as exc:
        outcome = type(exc).__name__
        log.exception("job %s failed", log_ref(job.url))
        await _status(bot, job, Failed(str(exc) or type(exc).__name__).user_message)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        log.info("job %s outcome=%s secs=%.1f", log_ref(job.url), outcome, time.monotonic() - started)
