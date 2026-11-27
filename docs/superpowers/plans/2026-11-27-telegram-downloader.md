# Telegram Media Downloader Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single-owner Telegram bot, running on the owner's Linux PC, that takes Instagram/X links and replies with the media files.

**Architecture:** Telegram-independent `bot/engine/` package (URL parsing, pacing, gallery-dl/yt-dlp subprocess wrappers, ffmpeg fitting) exposing one `download()` coroutine. A thin Telegram layer (`python-telegram-bot`, long polling) adds auth, a single-worker job queue, send planning and commands. Runs as a systemd user service.

**Tech Stack:** Python 3.12, uv, python-telegram-bot ≥21 (async), httpx, python-dotenv, gallery-dl, yt-dlp, ffmpeg/ffprobe, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-11-27-telegram-downloader-design.md`

## Global Constraints

- Project root: `/home/rajveer/Projects/Personal/media-grab-bot`. All paths below are relative to it.
- Only Telegram user IDs in `ALLOWED_USER_IDS` get any response; others dropped silently, logged as `rejected user <id>`.
- Telegram limits: `TELEGRAM_MAX_BYTES = 50 * 1024 * 1024`; `PHOTO_MAX_BYTES = 10 * 1024 * 1024`; media groups 2–10 items.
- Instagram pacing: ≥5 s + random 0–3 s jitter between Instagram network actions; gallery-dl `sleep-request=5.0-8.0`; on rate-limit pause Instagram for 600 s.
- X: never pass cookies to any X request; never contact fxtwitter/vxtwitter/fixupx (rewrite those links to `x.com`).
- gallery-dl always runs with `--config-ignore`; yt-dlp always with `--ignore-config` (no user config can inject cookies or change output).
- Secrets (bot token, every cookie value) never appear in logs or chat. Anything user-visible or logged goes through `scrub()`.
- `.env`, cookie files and `downloads/` are git-ignored; `.env` and cookie files chmod 600.
- Each job uses its own `job-*` temp dir under `DOWNLOAD_DIR`, removed in `finally`. Startup removes only leftover `job-*` dirs.
- User-facing error copy (exact):
  - `LoginRequired`: `Instagram login expired — refresh cookies`
  - `NoCookies`: `No Instagram cookies file — send one with /cookies`
  - `NotFound`: `Post not found or not visible to your account`
  - `RateLimited`: `Instagram is rate-limiting; try again in a while`
  - `InstagramPaused`: `Instagram paused for ~{minutes} more min after rate-limiting; send again later`
  - `XLoginRequired`: `This tweet needs an X login, which this bot doesn't use`
  - `Unsupported`: `Send an Instagram or X link`
  - `TooLarge`: `File is {mb} MB — over Telegram's 50 MB limit` (mb rounded to int)
  - `Failed`: `Download failed: {reason}` (reason scrubbed, ≤200 chars)
- Pin all deps in `uv.lock`; `yt-dlp` and `gallery-dl` have no upper bound in `pyproject.toml` and are upgraded by `scripts/update.sh`.

## Review Focus

1. **Bot token in HTTP logs.** python-telegram-bot's httpx logs request URLs (`https://api.telegram.org/bot<TOKEN>/...`) at INFO. Expect: token never in output. → Task 1 `test_httpx_request_log_hides_token`.
2. **Real share-menu text.** `Check this out https://www.instagram.com/reel/ABC123/?igsh=xyz).` with tracking params and trailing punctuation. Expect: one clean link. → Task 2 `test_extract_share_menu_text`.
3. **Cookie file missing** when an Instagram job runs (first run, or deleted). Expect: `NoCookies` message, no crash, no gallery-dl call. → Task 7 `test_instagram_without_cookie_file_raises_nocookies`.
4. **Downloader hangs** (network stall). Expect: process killed after timeout, job fails with message, the next queued job still runs. → Task 3 `test_run_timeout_kills_and_raises`, Task 10 `test_queue_continues_after_failure`.
5. **Downloader "succeeds" with zero files** (expired story, empty carousel). Expect: `NotFound`, not an empty send or crash. → Task 5 `test_zero_files_is_notfound`.

---

### Task 1: Scaffold, config, errors, secret scrubbing, logging

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `bot/__init__.py`, `bot/engine/__init__.py`, `bot/engine/models.py`, `bot/engine/errors.py`, `bot/config.py`, `bot/logsetup.py`, `tests/conftest.py`
- Test: `tests/test_errors.py`, `tests/test_config.py`, `tests/test_logsetup.py`

**Interfaces:**
- Produces:
  - `bot.engine.models`: `Platform(Enum)`: `INSTAGRAM`, `X`. `@dataclass(frozen=True) LinkRef(platform: Platform, kind: Literal["post","reel","tv","story","status","short"], url: str, key: str)`. `@dataclass MediaItem(path: Path, kind: Literal["video","image","gif"], size: int, width: int|None=None, height: int|None=None, duration: float|None=None, has_audio: bool=True)`. `@dataclass Result(items: list[MediaItem], author: str|None, source_url: str)`.
  - `bot.engine.errors`: base `DownloadError(Exception)` with `user_message: str` property; subclasses `LoginRequired`, `NoCookies(LoginRequired)`, `NotFound`, `RateLimited`, `InstagramPaused(seconds: float)`, `XLoginRequired`, `Unsupported`, `TooLarge(size_bytes: int)`, `Failed(reason: str)`. `register_secret(value: str) -> None`, `scrub(text: str) -> str`, `classify(platform: Platform, stderr: str) -> DownloadError`.
  - `bot.config`: `@dataclass(frozen=True) Config(bot_token: str, allowed_user_ids: frozenset[int], instagram_cookies: Path, download_dir: Path)`; `load_config(env: Mapping[str, str]) -> Config` (raises `ConfigError`); registers token via `register_secret`.
  - `bot.logsetup`: `setup_logging(level: int = logging.INFO) -> None`; `ScrubbingFilter(logging.Filter)`.

- [ ] **Step 1: Scaffold project**

`git init`; `uv init --package`-style layout by hand: `pyproject.toml` with project `media-grab-bot`, `requires-python = ">=3.12"`, deps `python-telegram-bot>=21`, `httpx`, `python-dotenv`, `yt-dlp`, `gallery-dl`; dev group `pytest`, `pytest-asyncio`; `[tool.pytest.ini_options] asyncio_mode = "auto"`. `.gitignore`: `.venv/`, `.env`, `*.cookies.txt`, `cookies/`, `downloads/`, `__pycache__/`. `.env.example` with `BOT_TOKEN=`, `ALLOWED_USER_IDS=`, `INSTAGRAM_COOKIES=./cookies/instagram.cookies.txt`, `DOWNLOAD_DIR=./downloads`. Run `uv sync`.
Expected: `uv run python -c "import telegram, yt_dlp, gallery_dl"` exits 0.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_errors.py
def test_scrub_registered_secret():
    register_secret("supersecretvalue")
    assert scrub("cookie supersecretvalue here") == "cookie *** here"

def test_scrub_bot_token_pattern():
    assert "AAH" not in scrub("POST https://api.telegram.org/bot123456789:AAHfakefakefakefakefakefakefakefake12/getMe")

def test_scrub_sessionid_forms():
    for s in ["sessionid=abc123%3Axyz", "sessionid\tabc123%3Axyz", '"sessionid": "abc123%3Axyz"']:
        assert "abc123" not in scrub(s)

def test_scrub_ignores_short_secrets():
    register_secret("ab")          # <4 chars never registered
    assert scrub("abc") == "abc"

@pytest.mark.parametrize("stderr,cls", [
    ("ERROR: HTTP Error 429: Too Many Requests", RateLimited),
    ("[instagram][error] Please wait a few minutes before you try again.", RateLimited),
    ("[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)", LoginRequired),
    ("ERROR: checkpoint_required", LoginRequired),
    ("[instagram][error] HTTP Error 404: Not Found", NotFound),
    ("ERROR: Requested content is not available", NotFound),
    ("[instagram][error] something odd", Failed),
])
def test_classify_instagram(stderr, cls):
    assert type(classify(Platform.INSTAGRAM, stderr)) is cls

@pytest.mark.parametrize("stderr,cls", [
    ("ERROR: [twitter] 123: NSFW tweet requires authentication", XLoginRequired),
    ("ERROR: [twitter] 123: Requested tweet is unavailable", NotFound),
    ("ERROR: [twitter] HTTP Error 404", NotFound),
    ("ERROR: weird", Failed),
])
def test_classify_x(stderr, cls):
    assert type(classify(Platform.X, stderr)) is cls

def test_x_429_does_not_raise_ratelimited():
    assert type(classify(Platform.X, "HTTP Error 429")) is Failed

def test_failed_reason_is_last_error_line_scrubbed_and_truncated():
    register_secret("tok-secret-123")
    err = classify(Platform.X, "noise\nERROR: boom tok-secret-123 " + "x" * 500)
    assert err.user_message.startswith("Download failed: ERROR: boom ***")
    assert len(err.user_message) <= len("Download failed: ") + 200

def test_user_messages_exact():
    assert InstagramPaused(125).user_message == "Instagram paused for ~3 more min after rate-limiting; send again later"
    assert TooLarge(73_400_320).user_message == "File is 70 MB — over Telegram's 50 MB limit"
    assert NoCookies().user_message == "No Instagram cookies file — send one with /cookies"
```

```python
# tests/test_config.py
def test_load_config_parses_ids_and_paths(tmp_path):
    cfg = load_config({"BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": "111, 222",
                       "INSTAGRAM_COOKIES": str(tmp_path/"c.txt"), "DOWNLOAD_DIR": str(tmp_path/"dl")})
    assert cfg.allowed_user_ids == frozenset({111, 222})
    assert cfg.download_dir == tmp_path/"dl"

@pytest.mark.parametrize("missing", ["BOT_TOKEN", "ALLOWED_USER_IDS"])
def test_load_config_requires(missing): ...  # raises ConfigError naming the variable

def test_load_config_rejects_non_numeric_ids(): ...  # "abc" → ConfigError
def test_defaults(): ...  # INSTAGRAM_COOKIES → Path("cookies/instagram.cookies.txt"), DOWNLOAD_DIR → Path("downloads")
```

```python
# tests/test_logsetup.py
def test_httpx_request_log_hides_token(caplog):
    register_secret("123456789:AAHrealtokenrealtokenrealtoken12")
    setup_logging()
    logging.getLogger("httpx").warning('HTTP Request: POST https://api.telegram.org/bot123456789:AAHrealtokenrealtokenrealtoken12/getUpdates')
    assert "AAHreal" not in caplog.text

def test_httpx_info_suppressed():
    setup_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
```

`tests/conftest.py`: autouse fixture clearing the secret registry between tests.

- [ ] **Step 3: Run tests — expect FAIL (import errors)**

Run: `uv run pytest tests/test_errors.py tests/test_config.py tests/test_logsetup.py -v`

- [ ] **Step 4: Implement models, errors, config, logsetup**

- `scrub`: replace registered secrets (len ≥4, longest first) with `***`; regex `\d{6,}:[A-Za-z0-9_-]{30,}` → `***`; regex `(sessionid|csrftoken|ds_user_id|mid|ig_did)(["']?\s*[:=\t]\s*["']?)[^\s;"']+` → `\1\2***`.
- `classify` checks lowercase stderr, first match wins. Instagram: rate (`429`, `too many requests`, `please wait a few minutes`) → login (`login`, `checkpoint_required`, `401`) → not-found (`404`, `not found`, `not available`, `private`) → `Failed`. X: login (`requires authentication`, `nsfw`, `log in`, `login`, `age-restricted`, `not authorized`) → not-found (`404`, `unavailable`, `not found`, `no status found`) → `Failed`. `Failed` reason = last stderr line containing `ERROR` else last non-empty line, scrubbed, cut to 200 chars.
- `InstagramPaused.user_message` minutes = `math.ceil(seconds / 60)`.
- `setup_logging`: basicConfig to stdout, format `%(asctime)s %(levelname)s %(name)s: %(message)s`; attach `ScrubbingFilter` to root **handlers** (so third-party loggers are covered; filter rewrites `record.msg = scrub(record.getMessage())`, `record.args = ()`); set `httpx` and `httpcore` loggers to WARNING.

- [ ] **Step 5: Run tests — expect PASS**

Run: `uv run pytest -v`

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: scaffold project with config, typed errors and secret scrubbing"
```

---

### Task 2: URL extraction, normalization, short-link resolution

**Files:**
- Create: `bot/engine/urls.py`
- Test: `tests/test_urls.py`

**Interfaces:**
- Consumes: `LinkRef`, `Platform`, `Unsupported`.
- Produces: `classify_url(url: str) -> LinkRef | None`; `extract_links(text: str) -> list[LinkRef]`; `async resolve(ref: LinkRef, http: httpx.AsyncClient) -> LinkRef` (raises `Unsupported` if the final URL is not supported).

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("url,platform,kind,norm,key", [
    ("https://www.instagram.com/reel/ABC123/?igsh=xyz", INSTAGRAM, "reel", "https://www.instagram.com/reel/ABC123/", "ABC123"),
    ("https://instagram.com/reels/ABC123", INSTAGRAM, "reel", "https://www.instagram.com/reel/ABC123/", "ABC123"),
    ("https://www.instagram.com/p/Cx_-9/?img_index=2", INSTAGRAM, "post", "https://www.instagram.com/p/Cx_-9/", "Cx_-9"),
    ("https://www.instagram.com/some.user/p/Cx9/", INSTAGRAM, "post", "https://www.instagram.com/p/Cx9/", "Cx9"),
    ("https://www.instagram.com/tv/TV1/", INSTAGRAM, "tv", "https://www.instagram.com/tv/TV1/", "TV1"),
    ("https://www.instagram.com/stories/some.user/3141592653/?utm_source=ig", INSTAGRAM, "story", "https://www.instagram.com/stories/some.user/3141592653/", "some.user/3141592653"),
    ("https://www.instagram.com/stories/some.user/", INSTAGRAM, "story", "https://www.instagram.com/stories/some.user/", "some.user"),
    ("https://www.instagram.com/share/reel/BAbc12/", INSTAGRAM, "short", "https://www.instagram.com/share/reel/BAbc12/", "BAbc12"),
    ("https://instagr.am/p/Cx9/", INSTAGRAM, "short", "https://instagr.am/p/Cx9/", "Cx9"),
    ("https://x.com/someone/status/1790000000000000000?s=46&t=abc", X, "status", "https://x.com/someone/status/1790000000000000000", "1790000000000000000"),
    ("https://twitter.com/someone/status/179/photo/1", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://mobile.twitter.com/someone/status/179", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://fxtwitter.com/someone/status/179", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://vxtwitter.com/someone/status/179", X, "status", "https://x.com/someone/status/179", "179"),
    ("https://x.com/i/status/179", X, "status", "https://x.com/i/status/179", "179"),
    ("https://x.com/i/web/status/179", X, "status", "https://x.com/i/status/179", "179"),
    ("https://t.co/AbCdEf", X, "short", "https://t.co/AbCdEf", "AbCdEf"),
])
def test_classify_url(url, platform, kind, norm, key): ...

@pytest.mark.parametrize("url", ["https://www.instagram.com/some.user/", "https://x.com/someone",
                                 "https://youtube.com/watch?v=x", "https://www.instagram.com/accounts/login/"])
def test_classify_url_unsupported(url):
    assert classify_url(url) is None

def test_extract_share_menu_text():
    refs = extract_links("Check this out https://www.instagram.com/reel/ABC123/?igsh=xyz).")
    assert [r.url for r in refs] == ["https://www.instagram.com/reel/ABC123/"]

def test_extract_multiple_in_order_dedup():
    t = "a https://x.com/u/status/1 b https://www.instagram.com/p/P1/ c https://twitter.com/u/status/1"
    assert [r.key for r in extract_links(t)] == ["1", "P1"]

def test_extract_none():
    assert extract_links("hello https://example.com") == []

async def test_resolve_follows_redirect():
    # httpx.MockTransport: /share/reel/BAbc12/ → 302 Location https://www.instagram.com/reel/REAL1/?igsh=q
    assert (await resolve(classify_url("https://www.instagram.com/share/reel/BAbc12/"), client)).url == "https://www.instagram.com/reel/REAL1/"

async def test_resolve_login_redirect_uses_next_param():
    # final URL https://www.instagram.com/accounts/login/?next=%2Freel%2FREAL1%2F
    assert (await resolve(ref, client)).key == "REAL1"

async def test_resolve_tco_to_x(): ...           # t.co → x.com/u/status/9 → kind "status", key "9"
async def test_resolve_to_unsupported_raises(): ...  # t.co → https://example.com → Unsupported
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/test_urls.py -v`

- [ ] **Step 3: Implement `bot/engine/urls.py`**

Parse with `urllib.parse`; drop query and fragment for all canonical forms. URL finder regex `https?://[^\s<>"']+`, then strip trailing `).,!?;:'"]`. Instagram hosts: `instagram.com`, `www.instagram.com`, `m.instagram.com`; `instagr.am` → always `short`. X hosts: `x.com`, `twitter.com`, `mobile.twitter.com`, `www.` variants, `fxtwitter.com`, `vxtwitter.com`, `fixupx.com`, `fixvx.com`; `t.co` → `short`. `resolve`: `GET` with `follow_redirects=True`, `timeout=15`, max 5 redirects, no cookies; if final path starts `/accounts/login` and has `next`, classify `https://www.instagram.com` + `next`; a result of kind `short` again → `Unsupported`.

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** — `git commit -m "feat: parse and normalize Instagram/X links"`

---

### Task 3: Subprocess runner and Instagram pacer

**Files:**
- Create: `bot/engine/proc.py`, `bot/engine/pacing.py`
- Test: `tests/test_proc.py`, `tests/test_pacing.py`

**Interfaces:**
- Consumes: `Failed`.
- Produces:
  - `@dataclass ProcResult(returncode: int, stdout: str, stderr: str)`; `async run(args: list[str], timeout: float = 300) -> ProcResult` — raises `Failed("timed out after {int(timeout)}s")` on timeout. Type alias `ProcRunner = Callable[[list[str], float], Awaitable[ProcResult]]` used by later tasks for injection; callers always pass timeout explicitly (gallery-dl/yt-dlp 300, ffprobe 30, ffmpeg 900).
  - `class Pacer(min_interval: float = 5.0, jitter: float = 3.0, *, clock=time.monotonic, sleep=asyncio.sleep, rand=random.uniform)` with `async wait() -> None`, `pause(seconds: float = 600) -> None`, `paused_for() -> float`.

- [ ] **Step 1: Write failing tests**

```python
async def test_run_captures_output():
    r = await run([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])
    assert (r.returncode, r.stdout.strip(), r.stderr.strip()) == (3, "out", "err")

async def test_run_timeout_kills_and_raises():
    t0 = time.monotonic()
    with pytest.raises(Failed, match="timed out after 1s"):
        await run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert time.monotonic() - t0 < 5

async def test_pacer_first_wait_immediate(): ...         # fake clock/sleep: no sleep call
async def test_pacer_enforces_interval_plus_jitter():
    # rand returns 2.0; second wait 1.0s after first → sleep called with 6.0
async def test_pacer_no_sleep_when_interval_elapsed(): ...
def test_pacer_pause_and_remaining():
    # clock=100 → pause(600) → paused_for()==600; clock=400 → 300; clock=800 → 0
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement**

`run`: `asyncio.create_subprocess_exec(..., stdout=PIPE, stderr=PIPE, start_new_session=True)`; on `asyncio.wait_for` timeout `os.killpg(proc.pid, SIGKILL)`, await `proc.wait()`, raise. Decode `utf-8`, `errors="replace"`. `Pacer.wait` records time after sleeping; jitter = `rand(0, jitter)`.

- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: add subprocess runner with timeout and Instagram pacer"`

---

### Task 4: Media probing and size fitting

**Files:**
- Create: `bot/engine/media.py`
- Test: `tests/test_media.py`

**Interfaces:**
- Consumes: `run`, `ProcRunner`, `TooLarge`.
- Produces: `TELEGRAM_MAX_BYTES`, `PHOTO_MAX_BYTES`; `IMAGE_EXTS = {"jpg","jpeg","png","webp","heic"}`, `VIDEO_EXTS = {"mp4","mov","webm","mkv","m4v"}`; `kind_for_path(path: Path) -> Literal["video","image"] | None`; `@dataclass Probe(width: int|None, height: int|None, duration: float|None, has_audio: bool)`; `async probe(path: Path, proc_run: ProcRunner = run) -> Probe`; `video_bitrate_kbps(limit_bytes: int, duration_s: float, audio_kbps: int = 128, margin: float = 0.92) -> int`; `async fit_video(path: Path, duration: float, limit: int = TELEGRAM_MAX_BYTES, proc_run: ProcRunner = run) -> Path`.

- [ ] **Step 1: Write failing tests**

```python
def test_bitrate_math():
    assert video_bitrate_kbps(50 * 1024 * 1024, 60) == 6303
    assert video_bitrate_kbps(50 * 1024 * 1024, 3600) < 0

def test_kind_for_path():
    assert kind_for_path(Path("a.JPG")) == "image"; assert kind_for_path(Path("a.mp4")) == "video"
    assert kind_for_path(Path("a.json")) is None

# fixture `make_video(tmp_path, seconds, bitrate, audio=True)` builds a clip with ffmpeg lavfi testsrc (+ anullsrc / sine)
async def test_probe_real_file(make_video):
    p = await probe(make_video(seconds=2, bitrate="500k", size="320x240"))
    assert (p.width, p.height, p.has_audio) == (320, 240, True) and 1.5 < p.duration < 2.5

async def test_probe_silent(make_video):
    assert (await probe(make_video(seconds=1, audio=False))).has_audio is False

async def test_fit_video_noop_under_limit(make_video):
    v = make_video(seconds=1, bitrate="200k"); assert await fit_video(v, 1.0, limit=10_000_000) == v

async def test_fit_video_reencodes_under_limit(make_video):
    v = make_video(seconds=2, bitrate="5M")             # ~1.25 MB
    out = await fit_video(v, 2.0, limit=500_000)
    assert out.stat().st_size <= 500_000 and not v.exists()

async def test_fit_video_too_long_raises(make_video):
    v = make_video(seconds=1, bitrate="5M")
    with pytest.raises(TooLarge): await fit_video(v, 3600.0, limit=500_000)
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement**

`probe`: `ffprobe -v error -print_format json -show_streams -show_format`; first video stream width/height, `format.duration`, any audio stream → `has_audio`. Images: width/height from ffprobe too. `fit_video`: return as-is if size ≤ limit; `kbps < 200` → `TooLarge(size)`; else `ffmpeg -y -i in -c:v libx264 -preset veryfast -b:v {k}k -maxrate {k}k -bufsize {2k}k -c:a aac -b:a 128k -movflags +faststart <stem>.fit.mp4` (timeout 900); output still > limit → `TooLarge(original size)`; success → delete original, return new path.

- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: probe media and re-encode videos to fit Telegram limit"`

---

### Task 5: Instagram downloader

**Files:**
- Create: `bot/engine/instagram.py`
- Test: `tests/test_instagram.py`, fixtures in `tests/fixtures/instagram/`

**Interfaces:**
- Consumes: `LinkRef`, `Result`, `MediaItem`, `classify`, `NotFound`, `Failed`, `kind_for_path`, `run`/`ProcRunner`.
- Produces: `async download_instagram(ref: LinkRef, workdir: Path, cookies: Path, proc_run: ProcRunner = run) -> Result` — items in gallery-dl output order, `kind` "video"/"image", `size` set; width/height/duration filled later by the engine.

- [ ] **Step 1: Write failing tests** (fake `proc_run` that creates files in `workdir` and returns recorded stdout/stderr)

```python
async def test_args_contain_safety_flags(fake_run, tmp_path):
    await download_instagram(ref_post, tmp_path, cookies_path, proc_run=fake_run)
    a = fake_run.calls[0]
    assert a[:3] == [sys.executable, "-m", "gallery_dl"]
    for flag in ["--config-ignore", "--write-metadata", "--cookies"]: assert flag in a
    assert "sleep-request=5.0-8.0" in a and "cookies-update=false" in a and a[-1] == ref_post.url

async def test_carousel_order_and_author(fake_run_carousel, tmp_path):
    # stdout lists 3 files: 1.jpg, 2.mp4, 3.jpg (+ "# " skipped lines ignored); metadata json has "username": "some.user"
    r = await download_instagram(...)
    assert [i.kind for i in r.items] == ["image", "video", "image"] and r.author == "some.user"
    assert all(not i.path.suffix == ".json" for i in r.items)

async def test_zero_files_is_notfound(...):          # rc 0, empty stdout → NotFound
async def test_error_is_classified(...):             # rc 1, stderr "HTTP redirect to login page" → LoginRequired
async def test_reel_falls_back_to_ytdlp_on_generic_failure(...):
    # gallery-dl rc 1 "something odd"; second call is yt-dlp with "--ignore-config" and "--cookies"; returns 1 mp4
async def test_no_fallback_on_login_error(...):      # only one call made
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement**

gallery-dl args: `[sys.executable, "-m", "gallery_dl", "--config-ignore", "--cookies", cookies, "-D", workdir, "--write-metadata", "-o", "sleep-request=5.0-8.0", "-o", "cookies-update=false", ref.url]`. Parse stdout lines (strip leading `# `), keep existing paths under `workdir` whose `kind_for_path` is not None. Author: `username` from first `*.json` in `workdir` (confirm key with `uv run gallery-dl -K <post url>` during smoke test; fallback `owner_username`, else None). Fallback for kind `reel`/`tv` only when classify → `Failed`: yt-dlp `[sys.executable, "-m", "yt_dlp", "--ignore-config", "--cookies", cookies, "-o", f"{workdir}/%(autonumber)03d.%(ext)s", "--print", "after_move:%(uploader_id)s\t%(filepath)s", "--no-simulate", "--merge-output-format", "mp4", ref.url]`.

- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: Instagram downloader via gallery-dl with yt-dlp fallback"`

---

### Task 6: X downloader

**Files:**
- Create: `bot/engine/x.py`
- Test: `tests/test_x.py`

**Interfaces:**
- Consumes: as Task 5.
- Produces: `async download_x(ref: LinkRef, workdir: Path, proc_run: ProcRunner = run) -> Result`.

- [ ] **Step 1: Write failing tests**

```python
async def test_ytdlp_args_no_cookies(fake_run, tmp_path):
    await download_x(ref_status, tmp_path, proc_run=fake_run)
    a = fake_run.calls[0]
    assert a[:3] == [sys.executable, "-m", "yt_dlp"] and "--ignore-config" in a
    assert not any("cookie" in x.lower() for x in a)
    assert "b[filesize<50M]/b[filesize_approx<50M]/bv*[filesize<45M]+ba/b" in a

async def test_multi_video_tweet(...):        # stdout "someone\t<wd>/001.mp4\nsomeone\t<wd>/002.mp4" → 2 videos, author "someone"
async def test_image_tweet_uses_gallery_dl_without_cookies(...):
    # yt-dlp stderr "ERROR: [twitter] 179: No video could be found in this tweet"
    # second call gallery_dl with "--config-ignore" and no "--cookies"; 4 jpgs → 4 images
async def test_login_needed(...):             # stderr "NSFW tweet requires authentication" → XLoginRequired
async def test_zero_files_is_notfound(...)
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement**

yt-dlp args as in Task 5 fallback but **without** `--cookies`, plus `-f "b[filesize<50M]/b[filesize_approx<50M]/bv*[filesize<45M]+ba/b"` (best format under 50 MB if one exists, else best — the spec's "retry capped under 50 MB" in a single selector). Image fallback triggered by `no video could be found` in stderr: gallery-dl `--config-ignore -D workdir --write-metadata url`; author from metadata `author.name` (confirm with `-K`), else None.

- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: X downloader via yt-dlp with gallery-dl image fallback"`

---

### Task 7: Engine `download()` orchestration

**Files:**
- Create: `bot/engine/api.py`; re-export `download` from `bot/engine/__init__.py`
- Test: `tests/test_engine_api.py`

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces: `async download(url: str, workdir: Path, *, cookies: Path, pacer: Pacer, http: httpx.AsyncClient, ig=download_instagram, x=download_x, prober=probe, fitter=fit_video) -> Result`.

Rules:
1. `classify_url(url)` → None → `Unsupported`.
2. Instagram (before any Instagram network action, including resolving `share`/`instagr.am`): `pacer.paused_for() > 0` → `InstagramPaused(remaining)`; cookie file missing → `NoCookies`; then exactly one `await pacer.wait()` for the job.
3. `short` → `resolve()`; if a `t.co` resolves to Instagram, apply rule 2 then.
4. Dispatch; `RateLimited` from Instagram → `pacer.pause(600)` then re-raise.
5. Each item: probe (`width/height/duration/has_audio`). X video with `has_audio=False` → `kind="gif"`. Video > `TELEGRAM_MAX_BYTES` → `fitter`, update path/size. Image > `TELEGRAM_MAX_BYTES` → `TooLarge`.
6. Before reading cookies for a job, `register_secret` every cookie value in the file (7-field tab lines, field 7).

- [ ] **Step 1: Write failing tests** (fakes for ig/x/prober/fitter; fake Pacer recording calls)

```python
async def test_unsupported(): ...                                      # "https://example.com" → Unsupported
async def test_instagram_without_cookie_file_raises_nocookies(tmp_path):
    with pytest.raises(NoCookies): await download(IG_REEL, tmp_path, cookies=tmp_path/"missing.txt", ...)
    assert fake_ig.calls == []
async def test_paused_instagram_fails_fast(): ...                      # pacer.paused_for()=120 → InstagramPaused, no ig call, no wait
async def test_instagram_waits_once_including_share_resolution(): ...  # share link → pacer.wait called exactly 1×
async def test_ratelimit_pauses_pacer(): ...                           # ig raises RateLimited → pacer.pause(600) called, error propagates
async def test_x_does_not_touch_pacer_or_cookies(): ...
async def test_x_silent_video_becomes_gif(): ...
async def test_oversized_video_is_fitted(): ...                        # size 60MB → fitter called, Result path = fitter output
async def test_cookie_values_registered(tmp_path): ...                 # after download, scrub("<sessionid value>") == "***"
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement `bot/engine/api.py`**
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: engine download orchestration with pacing and size fitting"`

---

### Task 8: Cookie file validation and atomic write

**Files:**
- Create: `bot/cookies.py`
- Test: `tests/test_cookies.py`

**Interfaces:**
- Produces: `MAX_COOKIE_FILE_BYTES = 1_000_000`; `validate_cookies(data: bytes) -> bool`; `write_cookies_atomic(path: Path, data: bytes) -> None`; `cookie_age(path: Path) -> timedelta | None`.

- [ ] **Step 1: Write failing tests**

```python
VALID = b"# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\t123%3Aabc\n"
def test_valid(): assert validate_cookies(VALID)
def test_valid_without_header(): assert validate_cookies(VALID.split(b"\n", 1)[1])
@pytest.mark.parametrize("data", [b"", b"\xff\xfe", b"hello", VALID.replace(b"sessionid", b"csrftoken"),
    VALID.replace(b".instagram.com", b".x.com"), VALID.replace(b"123%3Aabc", b""), b"a" * 1_000_001])
def test_invalid(data): assert not validate_cookies(data)
def test_write_atomic_sets_600(tmp_path):
    p = tmp_path/"cookies"/"ig.txt"; write_cookies_atomic(p, VALID)
    assert p.read_bytes() == VALID and stat.S_IMODE(p.stat().st_mode) == 0o600
    assert list(p.parent.iterdir()) == [p]            # no temp file left
def test_cookie_age_missing(tmp_path): assert cookie_age(tmp_path/"nope") is None
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** — temp file in same dir via `tempfile.mkstemp`, `os.fchmod(fd, 0o600)`, write, fsync, `os.replace`; parent dir created with mode 0o700.
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: validate and atomically store Instagram cookies"`

---

### Task 9: Send planning and execution

**Files:**
- Create: `bot/sender.py`
- Test: `tests/test_sender.py`

**Interfaces:**
- Consumes: `Result`, `MediaItem`, `PHOTO_MAX_BYTES`.
- Produces:
  - `@dataclass SendSingle(method: Literal["video","animation","photo","document"], item: MediaItem, caption: str|None)`; `@dataclass SendGroup(kind: Literal["visual","document"], items: list[MediaItem], caption: str|None)`; `SendOp = SendSingle | SendGroup`.
  - `caption_for(result: Result) -> str` → `"@{author}\n{source_url}"` or just `source_url` when author is None.
  - `plan_sends(result: Result, hq: bool) -> list[SendOp]` — caption only on the first op.
  - `async execute(bot: telegram.Bot, chat_id: int, ops: list[SendOp]) -> None`.

Planning rules: single item → video→`video`, gif→`animation`, image→`photo` unless `hq` or size > `PHOTO_MAX_BYTES` → `document`. Multiple items: gifs → own `animation` ops; images that must be documents (hq or >10 MB) → `document` groups; remaining photos+videos → `visual` groups. Order: visual groups, document groups, animations. Chunk groups by 10; a chunk of 1 becomes a `SendSingle`.

- [ ] **Step 1: Write failing tests**

```python
def test_single_video(): assert plan_sends(R([vid()]), hq=False) == [SendSingle("video", v, "@u\nhttps://x")]
def test_single_big_image_is_document(): ...           # size 11 MB → "document"
def test_hq_single_image_is_document(): ...
def test_carousel_12_items_chunks_10_and_2(): ...      # → [SendGroup visual 10 items (caption), SendGroup visual 2 items (None)]
def test_carousel_11_items_leftover_single(): ...      # → [SendGroup 10, SendSingle photo]
def test_hq_mixed_splits_documents_from_videos(): ...  # 2 img + 2 vid, hq → [SendGroup visual [vid,vid] cap, SendGroup document [img,img]]
def test_gif_never_in_group(): ...                     # 2 img + 1 gif → [SendGroup visual [img,img] cap, SendSingle animation]
def test_caption_without_author(): ...
async def test_execute_calls_bot_methods(): ...        # AsyncMock bot: send_video gets supports_streaming=True, width/height/duration; send_media_group gets InputMediaPhoto/InputMediaVideo list with caption on first
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** — `execute` opens files with `open(path, "rb")` in a `contextlib.ExitStack`; videos/animations pass `width`, `height`, `duration` (int), `supports_streaming=True` for video.
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: plan and send media to Telegram"`

---

### Task 10: Job queue and job worker

**Files:**
- Create: `bot/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `download`, `DownloadError`, `scrub`, `plan_sends`, `execute`, `Config`.
- Produces:
  - `@dataclass Job(chat_id: int, url: str, status_message_id: int)`.
  - `class JobQueue(worker: Callable[[Job], Awaitable[None]])`: `submit(job) -> int` (jobs ahead = pending + 1 if a job is running), `pending_count() -> int`, `async run_forever() -> None` (a worker exception is logged and the loop continues).
  - `async process_job(job: Job, *, bot, config: Config, pacer: Pacer, http, hq: Callable[[], bool], downloader=download, executor=execute) -> None`.
  - `log_ref(url: str) -> str` → host + path without query (e.g. `instagram.com/reel/ABC123`).
  - `wipe_leftovers(download_dir: Path) -> int` — removes only `job-*` dirs; returns count.

`process_job` lifecycle: edit status message to `⏳ Downloading…`; `workdir = mkdtemp(prefix="job-", dir=config.download_dir)`; download → plan → execute → delete status message; `DownloadError` → edit status message to `err.user_message`; any other exception → edit to `Failed(scrub(str(e))).user_message` and `log.exception`; `finally` `shutil.rmtree(workdir)`. Log one line: `job <log_ref> outcome=<ok|ErrorClass> secs=<n.n>`.

- [ ] **Step 1: Write failing tests**

```python
async def test_submit_reports_jobs_ahead(): ...          # worker blocked on Event: submits return 0, 1, 2
async def test_queue_continues_after_failure(): ...      # worker raises on job1; job2 still processed
async def test_success_deletes_status_and_workdir(tmp_path): ...  # fake bot; download dir has no job-* dirs after
async def test_download_error_edits_status_with_user_message(): ...   # NotFound → edit text "Post not found or not visible to your account"
async def test_unexpected_error_is_scrubbed(): ...       # downloader raises RuntimeError("boom <registered secret>") → text has "***", not secret
async def test_send_failure_still_cleans_workdir(): ...  # executor raises → workdir removed
async def test_hq_flag_passed_to_plan(): ...
def test_log_ref_strips_query(): assert log_ref("https://www.instagram.com/reel/A/?igsh=1") == "instagram.com/reel/A"
def test_wipe_leftovers_only_job_dirs(tmp_path): ...     # job-a, job-b removed; keep.txt and other/ kept; returns 2
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement** — `asyncio.Queue`; `submit` uses `put_nowait`.
- [ ] **Step 4: Run — expect PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: single-worker job queue with status messages and cleanup"`

---

### Task 11: Telegram handlers, auth, commands, entrypoint

**Files:**
- Create: `bot/telegram_bot.py`, `bot/__main__.py`
- Test: `tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `is_allowed(user_id: int | None, allowed: frozenset[int]) -> bool`.
  - `status_text(*, pending: int, ytdlp: str, gallerydl: str, cookie_age: timedelta | None, paused_for: float) -> str`.
  - `async handle_cookies_document(update, context) -> None`, `async handle_text(update, context) -> None`, `cmd_start`, `cmd_hq`, `cmd_status`, `gate` (group -1).
  - `build_application(config: Config) -> telegram.ext.Application`.
  - `python -m bot` runs it.

Behaviour:
- `gate`: `TypeHandler(Update, gate)` in group `-1`; if `not is_allowed(update.effective_user.id …)` → log `rejected user <id>` and `raise ApplicationHandlerStop`. No reply.
- `/start`: short help — what links work, `/hq on|off`, `/status`, `/cookies` (send cookies.txt as a file with caption `/cookies`).
- `/hq on|off` → `context.bot_data["hq"]`; replies `HQ on: images sent as original files` / `HQ off: images sent as photos`; other args → usage line.
- `/status` → `status_text(...)` with versions from `importlib.metadata.version("yt-dlp")`/`("gallery-dl")`; cookie age as `N days` or `missing`; IG paused line only if paused.
- Document with caption matching `^/cookies\b` (`filters.Document.ALL & filters.CaptionRegex(r"^/cookies\b")`): if `document.file_size > MAX_COOKIE_FILE_BYTES` treat invalid without downloading; else download to memory (`get_file()` → `download_as_bytearray()`); validate → `write_cookies_atomic(config.instagram_cookies, data)`; **always** `delete_message` the owner's message (on failure append `— couldn't delete your message, delete it manually`); reply `cookies updated` or `not a valid Instagram cookies file`. Never echo content.
- Text (`filters.TEXT & ~filters.COMMAND`): `extract_links`; none → reply `Unsupported().user_message`; for each link send status message (`⏳ Downloading…` if 0 ahead, else `⏳ Queued, {n} ahead`) then `queue.submit(Job(...))`.
- `build_application`: `ApplicationBuilder().token(...).read_timeout(60).write_timeout(300).media_write_timeout(300).post_init(start_worker)`; `start_worker` creates the shared `httpx.AsyncClient`, `Pacer()`, `JobQueue`, starts `run_forever` as a task; store all in `bot_data`. `post_shutdown` closes the client.
- `__main__`: `load_dotenv()` if `.env` exists; `load_config(os.environ)`; `setup_logging()`; create `download_dir` (0o700); `wipe_leftovers`; `app.run_polling(allowed_updates=Update.ALL_TYPES)`. `ConfigError` → print message, exit 2.

- [ ] **Step 1: Write failing tests** (handlers driven with `MagicMock`/`AsyncMock` updates and context)

```python
def test_is_allowed(): assert is_allowed(1, frozenset({1})) and not is_allowed(2, frozenset({1})) and not is_allowed(None, frozenset({1}))
async def test_gate_blocks_and_logs(caplog): ...       # raises ApplicationHandlerStop; "rejected user 2" in log; no reply sent
async def test_cookies_valid_writes_deletes_replies(tmp_path): ...  # file written 0o600; message.delete awaited; reply "cookies updated"
async def test_cookies_invalid_still_deletes(): ...    # reply "not a valid Instagram cookies file"; file untouched
async def test_cookies_oversize_not_downloaded(): ...  # file_size 2_000_000 → get_file not awaited
async def test_cookies_delete_failure_mentions_manual(): ...
async def test_text_without_links_replies_unsupported(): ...
async def test_text_two_links_queues_two_jobs(): ...   # second status message "⏳ Queued, 1 ahead"
async def test_hq_toggle(): ...
def test_status_text(): ...                            # contains "queue: 0", "yt-dlp 2026.x", "cookies: 3 days old"; "paused" absent when paused_for=0
```

- [ ] **Step 2: Run — expect FAIL**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run full suite — expect PASS** — `uv run pytest -v`
- [ ] **Step 5: Commit** — `git commit -m "feat: Telegram handlers, auth gate, commands and entrypoint"`

---

### Task 12: Deployment, update script, README, smoke test

**Files:**
- Create: `deploy/media-grab-bot.service`, `scripts/install.sh`, `scripts/update.sh`, `README.md`

**Interfaces:**
- Consumes: `python -m bot`.

- [ ] **Step 1: Write unit file**

`[Unit]` `After=network-online.target`, `Wants=network-online.target`. `[Service]` `WorkingDirectory=%h/Projects/Personal/media-grab-bot`, `ExecStart=%h/Projects/Personal/media-grab-bot/.venv/bin/python -m bot`, `Restart=on-failure`, `RestartSec=10`, `UMask=0077`. `[Install]` `WantedBy=default.target`.

- [ ] **Step 2: Write scripts**

`install.sh` (set -euo pipefail): `uv sync --frozen`; refuse if `.env` missing; `chmod 600 .env`; `mkdir -p -m 700 cookies downloads`; copy unit to `~/.config/systemd/user/`; `systemctl --user daemon-reload`; `systemctl --user enable --now media-grab-bot`; `loginctl enable-linger "$USER"`. `update.sh`: `uv lock --upgrade-package yt-dlp --upgrade-package gallery-dl && uv sync --frozen && systemctl --user restart media-grab-bot`, then print both versions.
Verify: `bash -n scripts/*.sh` exits 0; `systemd-analyze --user verify deploy/media-grab-bot.service` reports no errors.

- [ ] **Step 3: README**

Spec's owner setup steps 1–5 (BotFather token, @userinfobot ID, cookie export with "Get cookies.txt LOCALLY", fill `.env`, `scripts/install.sh`; recommendation of secondary IG account), cookie refresh (overwrite file or send with `/cookies`), `scripts/update.sh` when downloads start failing, `journalctl --user -u media-grab-bot -f` for logs, the privacy trade-off (Telegram sees links/files).

- [ ] **Step 4: Manual smoke test (owner's real bot)** — run `scripts/install.sh`, then from phone:
  - [ ] IG reel, IG carousel (mixed photo+video), IG story (single + all), IG post from a followed private account
  - [ ] Share-menu link from the Instagram app (`/share/` form)
  - [ ] X video, X GIF (arrives looping, no sound), X 4-image tweet, `t.co` link, X tweet needing login (gets X-login message)
  - [ ] Oversized X video (gets compressed or size message)
  - [ ] Expired/garbled cookies → login-expired message; `/cookies` valid + invalid upload (message deleted both times)
  - [ ] Message from a second Telegram account → no reply, `rejected user` in journal
  - [ ] `journalctl --user -u media-grab-bot | grep -E 'bot[0-9]+:|sessionid='` → no matches
  - [ ] `ls downloads/` empty after jobs; reboot PC → bot answers without logging in
  - [ ] While testing, confirm gallery-dl/yt-dlp metadata keys used for author (Tasks 5–6); fix if they differ

- [ ] **Step 5: Commit** — `git commit -m "chore: systemd service, install/update scripts and README"`
