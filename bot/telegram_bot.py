"""Telegram layer: auth gate, commands, link handling and app wiring."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version

import httpx
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application, ApplicationBuilder, ApplicationHandlerStop, CommandHandler, ContextTypes, MessageHandler,
    TypeHandler, filters,
)

from .config import Config
from .cookies import MAX_COOKIE_FILE_BYTES, cookie_age, validate_cookies, write_cookies_atomic
from .engine.errors import Unsupported
from .engine.pacing import Pacer
from .engine.urls import extract_links
from .jobs import DOWNLOADING, Job, JobQueue, process_job

log = logging.getLogger(__name__)

_COOKIES_CMD = re.compile(r"^/cookies\b")
FILE_HINT = "Send me links as text. To update Instagram cookies, send cookies.txt with caption /cookies"

HELP = (
    "Send me an Instagram or X link (or share one to me) and I'll send the media back.\n\n"
    "Works with: Instagram reels, posts, carousels, stories; X videos, GIFs and images.\n\n"
    "/hq on|off — send images as original files instead of photos\n"
    "/status — queue, tool versions, cookie age\n"
    "/cookies — send your Instagram cookies.txt as a file with caption /cookies "
    "(the message is deleted right away)"
)


def is_allowed(user_id: int | None, allowed: frozenset[int]) -> bool:
    return user_id is not None and user_id in allowed


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "?"


def status_text(*, pending: int, ytdlp: str, gallerydl: str, cookie_age: timedelta | None,
                paused_for: float) -> str:
    if cookie_age is None:
        cookies = "missing"
    elif cookie_age.days == 0:
        cookies = "less than a day old"
    else:
        cookies = f"{cookie_age.days} day{'s' if cookie_age.days != 1 else ''} old"
    lines = [f"queue: {pending} waiting", f"yt-dlp {ytdlp} · gallery-dl {gallerydl}", f"cookies: {cookies}"]
    if paused_for > 0:
        lines.append(f"Instagram paused: ~{-(-int(paused_for) // 60)} min")
    return "\n".join(lines)


async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    user = update.effective_user
    user_id = user.id if user else None
    if not is_allowed(user_id, config.allowed_user_ids):
        log.warning("rejected user %s", user_id)
        raise ApplicationHandlerStop


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP)


async def cmd_hq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    arg = (context.args[0].lower() if context.args else "")
    if arg == "on":
        context.bot_data["hq"] = True
        await update.effective_message.reply_text("HQ on: images sent as original files")
    elif arg == "off":
        context.bot_data["hq"] = False
        await update.effective_message.reply_text("HQ off: images sent as photos")
    else:
        state = "on" if context.bot_data.get("hq") else "off"
        await update.effective_message.reply_text(f"Usage: /hq on or /hq off (currently {state})")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    queue: JobQueue = context.bot_data["queue"]
    pacer: Pacer = context.bot_data["pacer"]
    await update.effective_message.reply_text(status_text(
        pending=queue.pending_count(), ytdlp=_pkg_version("yt-dlp"), gallerydl=_pkg_version("gallery-dl"),
        cookie_age=cookie_age(config.instagram_cookies), paused_for=pacer.paused_for(),
    ))


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any file from the owner: a cookies file is stored and its message deleted, with or
    without the /cookies caption, so a session file never stays in the chat."""
    config: Config = context.bot_data["config"]
    message = update.effective_message
    document = message.document
    is_cookies_cmd = bool(_COOKIES_CMD.match(message.caption or ""))
    valid = False
    try:
        if document.file_size is not None and document.file_size <= MAX_COOKIE_FILE_BYTES:
            tg_file = await document.get_file()
            data = bytes(await tg_file.download_as_bytearray())
            if validate_cookies(data):
                write_cookies_atomic(config.instagram_cookies, data)
                valid = True
    finally:
        deleted = False
        if is_cookies_cmd or valid:
            try:
                await message.delete()
                deleted = True
            except TelegramError:
                pass
    if not (is_cookies_cmd or valid):
        await message.reply_text(FILE_HINT)
        return
    text = "cookies updated" if valid else "not a valid Instagram cookies file"
    if not deleted:
        text += " — couldn't delete your message, delete it manually"
    log.info("cookies upload: %s", "accepted" if valid else "rejected")
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    queue: JobQueue = context.bot_data["queue"]
    message = update.effective_message
    refs = extract_links(message.text or "")
    if not refs:
        await message.reply_text(Unsupported().user_message)
        return
    for ref in refs:
        ahead = queue.jobs_ahead()
        text = DOWNLOADING if ahead == 0 else f"⏳ Queued, {ahead} ahead"
        status = await message.reply_text(text)
        queue.submit(Job(update.effective_chat.id, ref.url, status.message_id))


async def _post_init(app: Application) -> None:
    config: Config = app.bot_data["config"]
    http = httpx.AsyncClient(timeout=15)
    pacer = Pacer()

    async def worker(job: Job) -> None:
        await process_job(job, bot=app.bot, config=config, pacer=pacer, http=http,
                          hq=lambda: bool(app.bot_data.get("hq")))

    queue = JobQueue(worker)
    app.bot_data.update(http=http, pacer=pacer, queue=queue,
                        worker_task=asyncio.create_task(queue.run_forever()))
    log.info("bot started; allowed users: %d", len(config.allowed_user_ids))


async def _post_shutdown(app: Application) -> None:
    task = app.bot_data.get("worker_task")
    if task:
        task.cancel()
    http = app.bot_data.get("http")
    if http:
        await http.aclose()


def build_application(config: Config) -> Application:
    app = (
        ApplicationBuilder()
        .token(config.bot_token)
        .read_timeout(60)
        .write_timeout(300)
        .media_write_timeout(300)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data.update(config=config, hq=False)
    app.add_handler(TypeHandler(Update, gate), group=-1)
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("hq", cmd_hq))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
