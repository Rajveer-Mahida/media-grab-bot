#!/usr/bin/env bash
# One-time server preparation. Run as root ON THE SERVER (scripts/deploy.sh does it for you):
#   - installs ffmpeg without restarting any running services
#   - creates an unprivileged 'mediabot' user with home /opt/media-grab-bot
#   - installs uv for that user and the systemd unit (resource-capped)
set -euo pipefail
BASE=/opt/media-grab-bot

if ! command -v ffmpeg >/dev/null; then
  # NEEDRESTART_MODE=l: only list services needing restart, never restart them (production host)
  DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --no-install-recommends ffmpeg \
    || { DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get update -q &&
         DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --no-install-recommends ffmpeg; }
fi

id mediabot >/dev/null 2>&1 || useradd --system --create-home --home-dir "$BASE" --shell /usr/sbin/nologin mediabot
install -d -o mediabot -g mediabot -m 700 "$BASE" "$BASE/app" "$BASE/app/cookies" "$BASE/app/downloads"

if [[ ! -x "$BASE/.local/bin/uv" ]]; then
  sudo -u mediabot -H sh -c 'curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh' >/dev/null
fi
echo "server ready: ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3), uv $("$BASE/.local/bin/uv" --version | cut -d' ' -f2)"
