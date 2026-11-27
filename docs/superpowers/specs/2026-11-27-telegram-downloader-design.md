# Telegram Media Downloader Bot — Design

Date: 2026-11-27
Status: Approved by owner 2026-11-27

## Intent

A personal, self-hosted Telegram bot. Owner sends it an Instagram or X (Twitter)
link from their phone (via the share menu → Telegram); bot replies with the
media files, which the owner saves to their gallery.

**Why:** privacy. Public "downloader" websites see every link you paste and
often demand your account. This bot runs on the owner's own Linux PC and talks
only to Instagram, X and Telegram.

Accepted trade-off (owner decided): Telegram bot chats are not end-to-end
encrypted, so Telegram's servers see links and resulting files. Owner is fine
with this in exchange for convenience.

## Users

Exactly one: the owner. Used mainly from phone, sometimes laptop (Telegram
desktop/web). Bot uses the owner's own Instagram session so stories and
content from private accounts the owner follows work.

## Goals

1. Send a supported link → receive media back in the same chat, original quality
   where Telegram allows.
2. Supported content:
   - Instagram: reels (`/reel/`, `/reels/`), posts incl. carousels (`/p/`),
     IGTV-style video posts (`/tv/`), a single story
     (`/stories/<user>/<id>`), all current stories of a user
     (`/stories/<user>/`).
   - X: tweet with video, GIF or images (`x.com/.../status/<id>`,
     `twitter.com/...`, `mobile.twitter.com/...`, `fxtwitter`/`vxtwitter` links).
   - Short/share links: `instagram.com/share/...`, `instagr.am/...`, `t.co/...`,
     `x.com/i/status/<id>`. Designer's call: share/short links are resolved by
     following redirects (HEAD/GET, no cookies unless needed) inside the job, so
     the lookup counts toward Instagram pacing and the rate-limit pause. Content
     type is therefore decided after resolution, not at queue time.
3. Message can contain the link with surrounding text (that's what the share
   menu produces); bot extracts the first supported URL. Multiple links in one
   message → process each in order.
4. Only the owner can use it. Anyone else gets no response.
5. Clear status: bot replies "⏳ Downloading…" and edits/replaces it with the
   result or a plain-language error.
6. Nothing kept on disk after sending.
7. Low risk to the owner's Instagram account (see Rate limiting).
8. Runs unattended on the PC: starts on boot, restarts on crash.

## Non-goals (v1)

- Web UI / localhost page (planned later; engine must be reusable — see Structure).
- Telegram local Bot API server for 2 GB uploads.
- Bulk downloads: whole profiles, saved collections, all highlights.
- Other platforms (YouTube, TikTok, Facebook). yt-dlp makes them easy later;
  not in scope now.
- Instagram highlights. Nice if it falls out of gallery-dl for free; not required.
- Hosting on a VPS (datacenter IPs get blocked by Instagram; also hurts privacy).
- Multi-user support.

## Anti-goals (failure even if it "works")

- Anyone other than the owner can trigger downloads.
- Bot token or Instagram/X cookies leak: in logs, error messages sent to chat,
  or committed to git.
- Owner's Instagram account gets restricted because the bot hammers Instagram.
- Downloaded files pile up on disk.

## Constraints

- Host: owner's Linux PC (Python 3.12 present, ffmpeg installed). Must be on to work.
- Telegram Bot API (cloud) upload limit: 50 MB per file; photos via
  `sendPhoto` are capped at 10 MB and recompressed by Telegram.
- Media groups (albums): 2–10 items each.
- Instagram requires a logged-in session for stories and private accounts, and
  increasingly for public content too. Session = browser cookies exported to a
  Netscape `cookies.txt`. Cookies expire; owner must be able to refresh them
  without touching code.
- X is used **logged out** (owner decided: no X login, no third-party
  fallback services). Some tweets (age-restricted, some videos) will fail;
  that is accepted. Bot says so plainly instead of a generic failure.
- Extraction breaks whenever Instagram/X change their site; fix is usually
  "update yt-dlp / gallery-dl". Updating must be one command.

## Approaches considered

1. **Telegram bot only** — chosen. Easiest daily use, works the same on Android
   and iPhone, no network exposure (long polling, outbound only), fastest to build.
   Cost: Telegram sees links and files; 50 MB cap.
2. Private web app (PWA on Android / Apple Shortcut on iPhone, reached over home
   Wi-Fi or Tailscale). Most private, but needs auth, network setup and a
   per-phone share integration.
3. Both, sharing one download engine. Most capable, most work. Deferred: v1 is
   structured so the web page can be added on the same engine later.

## Decisions

Owner decided:
- Telegram bot (approach 1).
- Only the owner uses it, with the owner's own Instagram account.
- Runs on the owner's PC.
- `/cookies` upload via Telegram: kept (see below).
- Instagram cookies are optional (owner decided after first run, 2026-11-27): every
  Instagram link except stories is tried logged out first; only on failure is it retried
  with the owner's cookies. No cookies file → "needs an Instagram login — send your
  cookies.txt". Stories skip the logged-out attempt. Rate limiting never triggers the
  cookie retry.
- X: no login, no third-party fallback (fxtwitter/vxtwitter etc. are not
  contacted; such links are accepted as input only and rewritten to x.com).

Designer's calls (owner may override while reviewing):
- **Language/libs:** Python 3.12, `python-telegram-bot` (v21+, async),
  `gallery-dl` for Instagram (posts, carousels, stories), `yt-dlp` for X and as
  Instagram video fallback. Both are mature, actively maintained, and handle
  cookies. Run in a project virtualenv.
- **Connection:** long polling. No webhook, no open ports.
- **Auth:** allow-list of Telegram user IDs from config (one ID). Updates from
  anyone else are dropped silently and logged as a one-line "rejected user <id>".
- **Config:** `.env` file (`BOT_TOKEN`, `ALLOWED_USER_IDS`,
  `INSTAGRAM_COOKIES` path, `DOWNLOAD_DIR`).
  `.env` and cookie files chmod 600, git-ignored.
- **Cookie refresh:** owner exports cookies from their logged-in browser (e.g.
  "Get cookies.txt LOCALLY" extension) and overwrites the file. Bot reads the
  file per job, so no restart needed. Optional: owner can also send the
  `cookies.txt` file to the bot as a document with caption `/cookies` to replace
  it — only from the allowed user. Owner kept this feature. Designer's call:
  bot validates the file (Netscape format, contains an instagram.com
  `sessionid`), writes it atomically with chmod 600, then **deletes the
  owner's message containing the file** so it doesn't stay in chat history,
  and replies "cookies updated" without echoing contents. Invalid file →
  message still deleted, reply "not a valid Instagram cookies file". Accepted
  risk: Telegram's servers briefly held the session file.
- **Rate limiting:** one job at a time (in-process queue). At least 5 s between
  Instagram requests (gallery-dl `sleep-request`), small random jitter. If the
  owner sends many links at once, they queue and the bot reports position
  ("queued, 3 ahead").
- **Sending media:**
  - Single video → `sendVideo` (plays inline, saves to gallery), with
    `supports_streaming`, width/height/duration from ffprobe so it isn't shown
    square/stretched.
  - Single image → `sendPhoto` if ≤10 MB, else `sendDocument`.
  - Carousel / multiple stories / multi-image tweet → `sendMediaGroup` in
    chunks of 10.
  - GIFs from X (delivered as MP4) → `sendAnimation`.
  - Caption on the first item: author handle, the post's own text (caption /
    tweet text), and the original link (owner decided 2026-11-27 to include the
    post text). Over 1024 chars → media gets handle + link and the full text
    follows as separate message(s) of ≤4096 chars.
- **Quality vs 50 MB:** request best quality. If a video exceeds 50 MB, retry
  with yt-dlp format selection capped under 50 MB; if no such format exists,
  re-encode with ffmpeg to fit (target bitrate from duration). If still too big,
  reply with the size and that it's over Telegram's limit.
- **`/hq` toggle (small):** images normally sent as photos (Telegram
  recompresses). `/hq on` sends images as documents (original file, still
  saveable). Stored in memory/config; default off.
- **Errors:** map known failure types to short messages:
  - login required / cookies expired → "Instagram login expired — refresh cookies".
  - private / not found / deleted → "Post not found or not visible to your account".
  - rate limited (HTTP 429 / "please wait") → "Instagram is rate-limiting; try
    again in a while", and pause Instagram jobs for 10 minutes.
  - X tweet needs login → "This tweet needs an X login, which this bot doesn't use".
  - unsupported link → "Send an Instagram or X link".
  - anything else → "Download failed" + short reason; full traceback only in logs.
  Error text must be scrubbed of cookie/token values before sending or logging.
- **Temp files:** each job gets its own temp dir under `DOWNLOAD_DIR`,
  deleted after sending (success or failure). On startup, wipe leftovers.
- **Commands:** `/start` (short help), `/hq on|off`, `/cookies` (with file),
  `/status` (queue length, versions of yt-dlp/gallery-dl, whether the
  Instagram cookie file exists and its age).
- **Service:** systemd **user** service, `Restart=on-failure`, enabled with
  `loginctl enable-linger` so it runs without being logged in.
- **Updating extractors:** `make update` / script that upgrades yt-dlp and
  gallery-dl in the venv and restarts the service. Pin nothing for those two
  (they must track site changes); pin everything else.
- **Logging:** stdout → journald. Log job URL host + post id, outcome, duration.
  No cookies, no tokens.

## Structure

Engine is independent of Telegram so a web page can reuse it later.

```
media-grab-bot/
  bot/
    engine/        # url parsing + routing, downloaders, result model
      urls.py      # detect platform + content type from text
      instagram.py # gallery-dl wrapper (yt-dlp fallback)
      x.py         # yt-dlp wrapper
      media.py     # ffprobe metadata, size fitting / re-encode
      errors.py    # typed errors + secret scrubbing
    telegram_bot.py  # handlers, auth filter, queue, sending
    config.py
  tests/
  deploy/media-grab-bot.service
  scripts/update.sh
  .env.example
```

Engine API (shape, builder may refine): `download(url, workdir) -> Result`
where `Result` has a list of media items (path, kind: video|image|gif, width,
height, duration) plus author and canonical URL, or raises a typed error.

## Testing

- Unit tests (no network): URL detection on real share-menu text samples,
  auth filter, error classification + secret scrubbing, size-fitting decision
  logic, media-group chunking.
- Downloader wrappers tested with recorded/mocked gallery-dl/yt-dlp output.
- Manual smoke checklist against real links: IG reel, IG carousel (mixed
  photo+video), IG story, IG private-account post (followed), X video, X GIF,
  X 4-image tweet, oversized X video, expired cookies, `/cookies` upload
  (valid + invalid, message deleted in both), X tweet that needs login.

## Left to the builder

- Exact gallery-dl vs yt-dlp choice per Instagram content type, as long as
  all goal content types work.
- Calling the tools as Python libraries vs subprocess.
- Queue implementation, project tooling (uv/pip, Makefile vs scripts).
- Exact wording of bot messages.
- With `/hq on`, Telegram can't mix documents and videos in one album: send
  images as a document group and videos separately.

## Owner setup steps (to document in README)

1. Create bot with @BotFather → token.
2. Get own Telegram user ID (e.g. @userinfobot).
3. Export Instagram cookies from logged-in browser.
4. Fill `.env`, run install script, enable service.
5. Recommended: consider a secondary Instagram account to reduce risk to the
   main one (owner chose own account; this stays a recommendation).
