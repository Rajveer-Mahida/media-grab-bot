# media-grab-bot

A personal Telegram bot that runs on your own PC. Share an Instagram or X link to it
and it sends the media back: reels, posts and carousels, stories, X videos, GIFs and images.

- Only your Telegram account can use it. Everyone else is ignored.
- It talks only to Instagram, X and Telegram. No third-party downloader sites.
- Files are deleted from your PC as soon as they are sent.

**Privacy note:** Telegram bot chats are not end-to-end encrypted. Telegram's servers see
the links you send and the files the bot sends back.

## Setup

You need Linux, [uv](https://docs.astral.sh/uv/) and `ffmpeg` (`sudo apt install ffmpeg`).

1. **Create a bot.** In Telegram, message @BotFather and send `/newbot`. Copy the token it gives you.
2. **Get your Telegram user ID.** Message @userinfobot. It replies with your numeric ID.
3. **Export Instagram cookies.** In a desktop browser where you're logged into Instagram,
   install the "Get cookies.txt LOCALLY" extension. Open instagram.com and export the cookies.
   Save the file as `cookies/instagram.cookies.txt` in this folder.
   - This is your Instagram login, so treat it like a password.
   - You can also do this later from your phone. See "Refreshing cookies" below.
4. **Configure.** Run:
   ```bash
   cp .env.example .env
   ```
   Then fill in `BOT_TOKEN` and `ALLOWED_USER_IDS` (your ID from step 2).
5. **Install and start.** Run:
   ```bash
   scripts/install.sh
   ```
   The bot now runs in the background, starts when the PC boots, and restarts if it crashes.

**Recommended:** the bot uses your Instagram account. Downloading a lot very quickly can get
an account temporarily restricted. The bot spaces out its requests, but using a secondary
Instagram account for the cookies is safer.

## Using it

- On your phone, open the Instagram or X app and tap **Share → Telegram → your bot**,
  or paste a link into the chat.
- Several links in one message are handled one after another.
- `/hq on` sends images as original files instead of compressed photos. `/hq off` switches back.
- Sending a cookies.txt file is always recognised: the bot saves it and deletes the message, even without the `/cookies` caption.
- `/status` shows the queue, tool versions and how old your cookies are.

The bot works on X without logging in. Some tweets, such as age-restricted ones, need an
X login, and the bot will say so.

## Refreshing cookies

When the bot replies "Instagram login expired — refresh cookies", export fresh cookies
(setup step 3) in either of these ways:

- Overwrite `cookies/instagram.cookies.txt` on the PC. No restart is needed.
- Send the `cookies.txt` file to the bot as a **file** with the caption `/cookies`.
  The bot checks it, saves it, and deletes your message from the chat.

## When downloads start failing

Instagram and X change their sites often. Update the downloaders with:

```bash
scripts/update.sh
```

## Logs and maintenance

```bash
journalctl --user -u media-grab-bot -f        # live logs
systemctl --user restart media-grab-bot       # restart
systemctl --user stop media-grab-bot          # stop
uv run pytest                                 # run tests
```

Logs never contain your bot token or cookie values.
