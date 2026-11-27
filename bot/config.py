"""Configuration from environment variables (.env)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .engine.errors import register_secret


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_user_ids: frozenset[int]
    instagram_cookies: Path
    download_dir: Path


def _required(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"{name} is not set (see .env.example)")
    return value


def load_config(env: Mapping[str, str]) -> Config:
    token = _required(env, "BOT_TOKEN")
    raw_ids = _required(env, "ALLOWED_USER_IDS")
    try:
        ids = frozenset(int(part) for part in raw_ids.split(",") if part.strip())
    except ValueError:
        raise ConfigError("ALLOWED_USER_IDS must be comma-separated numeric Telegram user ids") from None
    if not ids:
        raise ConfigError("ALLOWED_USER_IDS is not set (see .env.example)")
    register_secret(token)
    return Config(
        bot_token=token,
        allowed_user_ids=ids,
        instagram_cookies=Path(env.get("INSTAGRAM_COOKIES") or "cookies/instagram.cookies.txt"),
        download_dir=Path(env.get("DOWNLOAD_DIR") or "downloads"),
    )
