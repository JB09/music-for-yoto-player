# Music for Yoto Player

Download audio (MP3) from YouTube and optionally upload directly to a Yoto Player MYO card.

**Two interfaces:**
- **Web UI** — step-by-step wizard in your browser (Docker or local)
- **CLI** — command-line tool for scripting

**Two ways to build your playlist:**
- **AI Chat** — describe what you want in natural language and Claude generates the song list
- **Text/Paste** — type or paste song names directly

**Then the pipeline runs:**
1. **Shuffle & Cap** — randomizes the list and limits to 12 songs (configurable)
2. **Search & Confirm** — searches YouTube Music, you pick the right match for each
3. **Download** — downloads audio as MP3 via yt-dlp
4. **Upload to Yoto** _(optional)_ — uploads to Yoto and creates a MYO card playlist

---

## Quick Start (Docker)

The fastest way to get running.

> **Note:** SSH key authentication must be set up with GitHub before cloning.
> See [GitHub's SSH guide](https://docs.github.com/en/authentication/connecting-to-github-with-ssh) if you haven't done this yet.
> Use the SSH clone URL (starts with `git@github.com:`) rather than HTTPS.

```bash
# 1. Clone the repo (use SSH URL)
git clone git@github.com:JB09/music-scraper-for-yoto-player.git
cd music-scraper-for-yoto-player

# 2. Create .env file with your API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 3. Run with Docker Compose
docker compose up --build
```

Open **http://localhost:5000** in your browser.

Downloaded MP3s are saved to the `./downloads/` folder on your host machine.

### Docker environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | For AI Chat | Anthropic API key for Claude |
| `YOTO_CLIENT_ID` | For Yoto upload | Yoto Developer API client ID |
| `YOTO_REDIRECT_URI` | No | Public base URL when behind a reverse proxy or custom domain (e.g. `https://yoto.example.com`). The `/yoto/callback` path is appended automatically. If not set, auto-detected from the request. |
| `FLASK_SECRET_KEY` | No | Auto-generated if not set. To set manually: `python3 -c "import secrets; print(secrets.token_hex(32))"` and add the output to your `.env` file. A fixed key ensures sessions survive container restarts. |

---

## Setup (Without Docker)

### Prerequisites (Windows)

1. **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
2. **FFmpeg** — Required for audio conversion
   - `winget install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

### Install

```bash
git clone <repo-url>
cd music-scraper-for-yoto-player

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

### Set API key (for AI Chat mode)

```bash
set ANTHROPIC_API_KEY=sk-ant-...
```
Get a key at [console.anthropic.com](https://console.anthropic.com/).

---

## Web UI

```bash
python web_app.py
```

Open **http://localhost:5000**. The wizard walks you through:

1. **Build** — AI chat or paste a song list
2. **Review** — see the shuffled/capped playlist, reshuffle if needed
3. **Match** — confirm the YouTube match for each song (one at a time)
4. **Download** — downloads all MP3s
5. **Yoto** _(optional)_ — upload to Yoto and create a MYO card

---

## CLI Usage

See **[CLI.md](CLI.md)** for full CLI documentation, including all commands, options, and song file format.

---

## Shuffle & Song Limit

By default, the song list is **randomized** and **capped at 12 songs**. This is designed for Yoto MYO cards where you typically want a manageable playlist for kids.

- Override the cap: `--max-songs 8` or `--max-songs 20`
- Disable shuffle: `--no-shuffle`
- The final list is always shown for confirmation before downloading

## Setting Up Yoto API Access

1. Go to [yoto.dev/get-started](https://yoto.dev/get-started/start-here/) and register for a developer account
2. Obtain your **Client ID** from the Yoto Developers portal
3. Pass it via `--yoto` flag (CLI) or `YOTO_CLIENT_ID` env var (Docker/Web)

### Authentication

Two OAuth2 flows are supported:

- **CLI** — Uses the [Device Code flow](https://yoto.dev/authentication/auth/). On first run it opens a browser for login. No callback URL needed.
- **Web UI** — Uses the [Authorization Code flow](https://yoto.dev/authentication/auth/). Click "Connect to Yoto" in the browser to log in. After authorization, Yoto redirects back to the app automatically.

### Callback URL Configuration (Web UI)

For the Web UI's OAuth flow to work, you must add a **callback URL** in the Yoto Developer portal:

1. Go to your app settings at [yoto.dev](https://yoto.dev/)
2. Find **Allowed Callback URLs**
3. Add your app's callback URL:
   - Local development: `http://localhost:5000/yoto/callback`
   - Docker: `http://localhost:5000/yoto/callback`
   - Reverse proxy / custom domain: `https://yourdomain.com/yoto/callback`
4. Multiple URLs can be comma-separated (e.g. for different environments)

> **Note:** All callback URLs must use `https://` in production. `http://` is only accepted for `localhost`.

**Using a reverse proxy or custom domain**

If the app runs behind a reverse proxy (e.g. `https://yoto.example.com`), the auto-detected callback URL will be wrong because the app sees `localhost` internally. Set the `YOTO_REDIRECT_URI` environment variable to your public base URL — the `/yoto/callback` path is appended automatically:

```bash
YOTO_REDIRECT_URI=https://yoto.example.com
```

Then add `https://yoto.example.com/yoto/callback` to the **Allowed Callback URLs** in the Yoto Developer portal.

Tokens are saved to `~/.yoto-scraper-tokens.json` and reused across sessions.

## How It Works

```
AI Chat  OR  Paste songs  OR  songs.txt
                │
                ▼
  [Shuffle & Cap] → randomize, limit to 12 songs → confirm list
                │
                ▼
  [Phase 1] Search YouTube Music → show top 5 results → you confirm each
                │
                ▼
  [Phase 2] Download audio via yt-dlp → convert to MP3 (192kbps)
                │
                ▼
  [Phase 3] Upload MP3s to Yoto API → create MYO card playlist
                │
                ▼
  Open Yoto app → link playlist to physical MYO card (NFC tap or insert)
```

## Card Icons

When uploading to Yoto, the app automatically selects a 16x16 pixel display icon for your MYO card. There are two modes:

- **Auto-select from public icons** _(default)_ — Fetches Yoto's shared icon library and uses AI to pick the best match based on your playlist name and song list (e.g. a music note for a music playlist, a moon for bedtime songs).
- **Generate custom icon** — Uses AI to generate a custom 16x16 pixel art PNG tailored to your playlist theme, then uploads it to your Yoto account.

The selected icon is set on every chapter of the card via the `display.icon16x16` field, which the Yoto Player shows during playback.

In the **Web UI**, choose the icon mode from the dropdown on the upload screen. In the **CLI**, icon selection runs automatically (public icon matching first, with generated fallback).

Icon requirements (per [Yoto Developer docs](https://yoto.dev/icons/uploading-icons/)):
- 16x16 pixels
- PNG (24-bit RGBA) or GIF
- Auto-convert is available for larger images

## MYO Card Limits

| Limit | Value |
|---|---|
| Max tracks per card | 100 |
| Max file size per track | 100 MB |
| Max total card size | 500 MB |
| Max total duration | 5 hours |
| Supported formats | MP3, M4A |

## File Structure

```
music-scraper-for-yoto-player/
├── web_app.py          # Flask web UI
├── templates/          # HTML templates for web UI
│   ├── base.html       #   Shared layout + styles
│   ├── index.html      #   Home (choose input mode)
│   ├── chat.html       #   AI chat interface
│   ├── text_input.html #   Paste song list
│   ├── review.html     #   Review shuffled playlist
│   ├── match.html      #   Confirm YouTube matches
│   ├── download.html   #   Download progress
│   └── results.html    #   Results + Yoto upload
├── yoto_scraper.py     # CLI application
├── playlist_chat.py    # AI chat playlist generator
├── yoto_client.py      # Yoto API client
├── icon_selector.py    # AI-powered card icon selection
├── songs.txt           # Song list (for CLI text mode)
├── Dockerfile          # Docker image
├── docker-compose.yml  # Docker Compose config
├── .env.example        # Environment variable template
├── requirements.txt    # Python dependencies
└── downloads/          # Downloaded MP3s
```

## Note on the Physical Card Step

Everything is automated except the final step: linking the playlist to a physical MYO card. This requires either:
- **NFC tap** via the Yoto mobile app (hold card to phone)
- **Insert card** into a connected Yoto Player

This is a hardware interaction that can't be automated via software.
