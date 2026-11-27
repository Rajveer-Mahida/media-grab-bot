#!/usr/bin/env bash
# Upgrade the downloaders (yt-dlp, gallery-dl) and restart the bot.
# Run this when downloads start failing after Instagram/X change their site.
set -euo pipefail
cd "$(dirname "$0")/.."

uv lock --upgrade-package yt-dlp --upgrade-package gallery-dl
uv sync --frozen
if systemctl --user is-enabled -q media-grab-bot 2>/dev/null; then systemctl --user restart media-grab-bot; fi
echo "yt-dlp $(.venv/bin/python -m yt_dlp --version) · gallery-dl $(.venv/bin/python -m gallery_dl --version)"
