#!/usr/bin/env bash
# Deploy the committed code (HEAD) to a server and (re)start the bot there.
#   scripts/deploy.sh <ssh-host>            e.g. scripts/deploy.sh gstride
# First run also: prepares the server and copies your local .env (and cookies, if any).
# Logs on the server: journalctl -u media-grab-bot -f
set -euo pipefail
HOST=${1:?usage: scripts/deploy.sh <ssh-host>}
cd "$(dirname "$0")/.."
APP=/opt/media-grab-bot/app

ssh "$HOST" 'bash -s' < scripts/server-setup.sh

git archive --format=tar HEAD | ssh "$HOST" "tar -x -C $APP"

if ! ssh "$HOST" "test -f $APP/.env"; then
  [[ -f .env ]] || { echo "No local .env to copy" >&2; exit 1; }
  scp -q .env "$HOST:$APP/.env"
fi
if [[ -f cookies/instagram.cookies.txt ]] && ! ssh "$HOST" "test -f $APP/cookies/instagram.cookies.txt"; then
  scp -q cookies/instagram.cookies.txt "$HOST:$APP/cookies/instagram.cookies.txt"
fi

ssh "$HOST" "set -e
  chown -R mediabot:mediabot /opt/media-grab-bot
  chmod 600 $APP/.env
  cd $APP && sudo -u mediabot -H /opt/media-grab-bot/.local/bin/uv sync --frozen --no-dev -q
  install -m 644 $APP/deploy/server/media-grab-bot.service /etc/systemd/system/media-grab-bot.service
  systemctl daemon-reload
  systemctl enable -q media-grab-bot
  systemctl restart media-grab-bot
  sleep 3
  systemctl is-active media-grab-bot"
