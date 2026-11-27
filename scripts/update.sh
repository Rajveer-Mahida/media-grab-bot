#!/usr/bin/env bash
# Upgrade the downloaders (yt-dlp, gallery-dl) and restart the bot.
# Run this when downloads start failing after Instagram/X change their site.
set -euo pipefail
cd "$(dirname "$0")/.."

uv lock --upgrade-package yt-dlp --upgrade-package gallery-dl
uv sync --frozen
systemctl --user restart media-grab-bot
echo "yt-dlp $(.venv/bin/python -m yt_dlp --version) · gallery-dl $(.venv/bin/python -m gallery_dl --version)"
