"""Turn a download Result into Telegram send operations, and perform them."""
from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import dataclass
from typing import Literal

from telegram import Bot, InputMediaDocument, InputMediaPhoto, InputMediaVideo

from .engine.media import PHOTO_MAX_BYTES
from .engine.models import MediaItem, Result

GROUP_MAX = 10
CAPTION_MAX = 1024  # Telegram limit for media captions
MESSAGE_MAX = 4096  # Telegram limit for text messages


@dataclass
class SendSingle:
    method: Literal["video", "animation", "photo", "document"]
    item: MediaItem
    caption: str | None


@dataclass
class SendGroup:
    kind: Literal["visual", "document"]
    items: list[MediaItem]
    caption: str | None


@dataclass
class SendText:
    text: str


SendOp = SendSingle | SendGroup | SendText


def _short_caption(result: Result) -> str:
    if result.author:
        return f"@{result.author}\n{result.source_url}"
    return result.source_url


def caption_for(result: Result) -> str:
    """@author, the post's own text, and the link — blank lines between."""
    if not result.text:
        return _short_caption(result)
    parts = [f"@{result.author}"] if result.author else []
    parts += [result.text, result.source_url]
    return "\n\n".join(parts)


def _chunks(items: list[MediaItem]) -> list[list[MediaItem]]:
    return [items[i:i + GROUP_MAX] for i in range(0, len(items), GROUP_MAX)]


def plan_sends(result: Result, hq: bool) -> list[SendOp]:
    visual: list[MediaItem] = []
    documents: list[MediaItem] = []
    animations: list[MediaItem] = []
    for item in result.items:
        if item.kind == "gif":
            animations.append(item)
        elif item.kind == "image" and (hq or item.size > PHOTO_MAX_BYTES):
            documents.append(item)
        else:
            visual.append(item)

    ops: list[SendOp] = []
    for chunk in _chunks(visual):
        if len(chunk) == 1:
            ops.append(SendSingle("video" if chunk[0].kind == "video" else "photo", chunk[0], None))
        else:
            ops.append(SendGroup("visual", chunk, None))
    for chunk in _chunks(documents):
        ops.append(SendSingle("document", chunk[0], None) if len(chunk) == 1 else SendGroup("document", chunk, None))
    ops.extend(SendSingle("animation", item, None) for item in animations)

    if ops:
        full = caption_for(result)
        if len(full) <= CAPTION_MAX:
            ops[0] = dataclasses.replace(ops[0], caption=full)
        else:
            ops[0] = dataclasses.replace(ops[0], caption=_short_caption(result))
            text = result.text or ""
            ops.extend(SendText(text[i:i + MESSAGE_MAX]) for i in range(0, len(text), MESSAGE_MAX))
    return ops


def _duration(item: MediaItem) -> int | None:
    return max(1, round(item.duration)) if item.duration else None


def _input_media(item: MediaItem, kind: str, fh, caption: str | None):
    if kind == "document":
        return InputMediaDocument(fh, caption=caption)
    if item.kind == "video":
        return InputMediaVideo(fh, caption=caption, width=item.width, height=item.height,
                               duration=_duration(item), supports_streaming=True)
    return InputMediaPhoto(fh, caption=caption)


async def execute(bot: Bot, chat_id: int, ops: list[SendOp]) -> None:
    for op in ops:
        if isinstance(op, SendText):
            await bot.send_message(chat_id=chat_id, text=op.text)
            continue
        with contextlib.ExitStack() as stack:
            if isinstance(op, SendGroup):
                media = [
                    _input_media(item, op.kind, stack.enter_context(open(item.path, "rb")),
                                 op.caption if i == 0 else None)
                    for i, item in enumerate(op.items)
                ]
                await bot.send_media_group(chat_id=chat_id, media=media)
                continue
            item = op.item
            fh = stack.enter_context(open(item.path, "rb"))
            if op.method == "video":
                await bot.send_video(chat_id=chat_id, video=fh, caption=op.caption, width=item.width,
                                     height=item.height, duration=_duration(item), supports_streaming=True)
            elif op.method == "animation":
                await bot.send_animation(chat_id=chat_id, animation=fh, caption=op.caption, width=item.width,
                                         height=item.height, duration=_duration(item))
            elif op.method == "photo":
                await bot.send_photo(chat_id=chat_id, photo=fh, caption=op.caption)
            else:
                await bot.send_document(chat_id=chat_id, document=fh, caption=op.caption)
