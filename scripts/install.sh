#!/usr/bin/env bash
# Install dependencies and run the bot as a systemd user service that starts on boot.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example to .env and fill in BOT_TOKEN and ALLOWED_USER_IDS first." >&2
  exit 1
fi
command -v ffmpeg >/dev/null || { echo "ffmpeg is required (sudo apt install ffmpeg)" >&2; exit 1; }

uv sync --frozen
chmod 600 .env
mkdir -p -m 700 cookies downloads
[[ -f cookies/instagram.cookies.txt ]] && chmod 600 cookies/instagram.cookies.txt

mkdir -p ~/.config/systemd/user
cp deploy/media-grab-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now media-grab-bot
loginctl enable-linger "$USER"

echo "Installed. Logs: journalctl --user -u media-grab-bot -f"
