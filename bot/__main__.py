"""Entry point: python -m bot"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update

from .config import ConfigError, load_config
from .jobs import wipe_leftovers
from .logsetup import setup_logging
from .telegram_bot import build_application


def main() -> None:
    if Path(".env").is_file():
        load_dotenv(".env")
    try:
        config = load_config(os.environ)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(2)
    setup_logging()
    config.download_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    removed = wipe_leftovers(config.download_dir)
    if removed:
        logging.getLogger("bot").info("removed %d leftover job folders", removed)
    try:
        build_application(config).run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception:
        # Logged (and scrubbed) instead of a raw traceback: errors like InvalidToken quote the token.
        logging.getLogger("bot").exception("bot stopped")
        sys.exit(1)


if __name__ == "__main__":
    main()
