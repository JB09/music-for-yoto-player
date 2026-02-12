# Music for Yoto Player

Search and download audio (MP3) from multiple music sources and optionally upload directly to a Yoto Player MYO card.

**Two interfaces:**
- **Web UI** — step-by-step wizard in your browser (Docker or local)
- **CLI** — command-line tool for scripting

**Two ways to build your playlist:**
- **AI Chat** — describe what you want in natural language and Claude generates the song list
- **Text/Paste** — type or paste song names directly

**Pluggable music providers:**
- **YouTube** _(default)_ — searches YouTube Music, downloads audio via [yt-dlp-host](https://github.com/Vasysik/yt-dlp-host) sidecar
- **Plex** — searches your Plex music library, retrieves audio directly from your server

**Then the pipeline runs:**
1. **Shuffle & Cap** — randomizes the list and limits to 12 songs (configurable)
2. **Search & Confirm** — searches your chosen music provider, you pick the right match for each
3. **Download** — retrieves audio as MP3
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

# 3. Run with Docker Compose (YouTube provider with yt-dlp sidecar)
docker compose --profile youtube up --build
```

Open **http://localhost:5000** in your browser.

Downloaded MP3s are saved to the `./downloads/` folder on your host machine.

### Docker environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | For AI Chat | Anthropic API key for Claude |
| `MUSIC_PROVIDER` | No | `youtube` (default) or `plex` |
| `DOWNLOAD_SERVICE_URL` | No | URL of yt-dlp-host sidecar (default: `http://ytdlp:5000`). If unset, falls back to local yt-dlp library |
| `DOWNLOAD_API_KEY` | No | API key for the yt-dlp-host service (if configured) |
| `PLEX_URL` | For Plex | Plex server URL (e.g. `http://192.168.1.100:32400`) |
| `PLEX_TOKEN` | For Plex | Plex authentication token |
| `PLEX_MUSIC_LIBRARY` | No | Plex music library name (default: `Music`) |
| `YOTO_CLIENT_ID` | For Yoto upload | Yoto Developer API client ID |
| `YOTO_REDIRECT_URI` | No | Public base URL when behind a reverse proxy or custom domain (e.g. `https://yoto.example.com`). The `/yoto/callback` path is appended automatically. If not set, auto-detected from the request. |
| `FLASK_SECRET_KEY` | No | Auto-generated if not set. To set manually: `python3 -c "import secrets; print(secrets.token_hex(32))"` and add the output to your `.env` file. A fixed key ensures sessions survive container restarts. |

---

## Music Providers

The app uses a pluggable provider interface to search for and retrieve audio. Set `MUSIC_PROVIDER` in your `.env` to choose which one.

### YouTube Provider (default)

> **Disclaimer:** Downloading audio from YouTube may violate YouTube's Terms of Service and/or copyright law in your jurisdiction. This project does not host, bundle, or distribute any download tools — it delegates to a user-provided sidecar service. **You are solely responsible for how you use this software and for complying with all applicable laws and terms of service.** The authors of this project assume no liability for misuse.

The YouTube provider searches YouTube Music (via [ytmusicapi](https://github.com/sigma67/ytmusicapi)) and retrieves audio via a separate download service.

**Architecture:** Audio downloading is handled by an external sidecar container rather than being built into this app. This separation means:

- This project **does not bundle yt-dlp or any YouTube download code** in its Docker image
- The download service is a **user-provided, independently-run container** that you choose to operate
- The recommended sidecar is [yt-dlp-host](https://github.com/Vasysik/yt-dlp-host), a lightweight REST API wrapper around yt-dlp

**How it works:**

1. The app searches YouTube Music for song matches (read-only metadata search)
2. When you confirm a song, the app sends a download request to the sidecar's REST API
3. The sidecar downloads and converts the audio to MP3
4. The app retrieves the MP3 file from the sidecar

**Setup with Docker Compose:**

The included `docker-compose.yml` defines a `ytdlp` service under the `youtube` profile. To start both the app and the sidecar:

```bash
docker compose --profile youtube up --build
```

Without the `--profile youtube` flag, only the main app starts (no download capability unless `DOWNLOAD_SERVICE_URL` points elsewhere or local yt-dlp is installed).

**Docker volumes and data flow:**

The two containers do **not** share a filesystem — all file transfer happens over HTTP:

1. The sidecar downloads audio into its own internal volume (`ytdlp-data`)
2. The main app requests the finished file via `GET /files/{path}` over the Docker network
3. The main app saves the MP3 to the host-mounted `./downloads/` directory

The sidecar uses two named Docker volumes (both persist across container restarts):

| Volume | Mount path | Purpose |
|---|---|---|
| `ytdlp-data` | `/app/downloads` | Temporary storage for downloaded audio inside the sidecar |
| `ytdlp-keys` | `/app/jsons` | Auth cookies / key data used by yt-dlp (persists across restarts so you don't need to re-authenticate) |

Your final MP3 files end up in `./downloads/` on the host (bind-mounted into the main app container). The sidecar's volumes are internal — you don't need to access them directly.

**Local fallback (without sidecar):**

If `DOWNLOAD_SERVICE_URL` is not set, the YouTube provider falls back to using the yt-dlp Python library directly. This requires:

```bash
pip install yt-dlp
# Plus ffmpeg on your PATH for MP3 conversion
```

This fallback is intended for local development. In Docker, ffmpeg is pre-installed in the image so the fallback works, but the sidecar approach is recommended.
### Plex Provider

The Plex provider searches your own Plex Media Server music library and retrieves audio files directly — no external downloads involved.

**Setup:**

```bash
# In .env
MUSIC_PROVIDER=plex
PLEX_URL=http://192.168.1.100:32400
PLEX_TOKEN=your-plex-token
PLEX_MUSIC_LIBRARY=Music  # optional, defaults to "Music"
```

```bash
# Install the Plex API client
pip install PlexAPI
```

The provider searches across track titles and artist names in your library. Audio retrieval copies files directly if already MP3, or requests server-side transcoding to MP3 for other formats (FLAC, etc.).

**Note:** YouTube preview (play button on the match screen) is not available with the Plex provider since tracks are local files, not YouTube videos.

## Note on the Physical Card Step

Everything is automated except the final step: linking the playlist to a physical MYO card. This requires either:
- **NFC tap** via the Yoto mobile app (hold card to phone)
- **Insert card** into a connected Yoto Player

This is a hardware interaction that can't be automated via software.

---

## CLI Usage

See **[CLI.md](CLI.md)** for full CLI documentation, including all commands, options, and song file format.

---

## Setting Up Yoto API Access

1. Go to [yoto.dev/get-started](https://yoto.dev/get-started/start-here/) and register for a developer account
2. Obtain your **Client ID** from the Yoto Developers portal
3. Pass it via `--yoto` flag (CLI) or `YOTO_CLIENT_ID` env var (Docker/Web)

### Callback URL Configuration (Web UI)

For the Web UI's OAuth flow to work, you must add a **callback URL** in the Yoto Developer portal:

1. Go to your app settings at [yoto.dev](https://yoto.dev/)
2. Find **Allowed Callback URLs**
3. Add your app's callback URL:
   - Docker: `http://localhost:5000/yoto/callback`
   - Reverse proxy / custom domain: `https://yourdomain.com/yoto/callback`
4. Multiple URLs can be comma-separated (e.g. for different environments)

> **Note:** All callback URLs must use `https://` in production. `http://` is only accepted for `localhost`.

**Using a reverse proxy or custom domain**

If the app runs behind a reverse proxy (e.g. `https://yoto.example.com`), the auto-detected callback URL will be wrong because the app sees `localhost` internally. Set the `YOTO_REDIRECT_URI` environment variable to your public base URL — the `/yoto/callback` path is appended automatically:

```bash
YOTO_REDIRECT_URI=https://yoto.example.com
```

Tokens are saved to `~/.yoto-scraper-tokens.json` and reused across sessions.

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

## File Structure

```
music-scraper-for-yoto-player/
├── web_app.py              # Flask web UI
├── music_providers/        # Pluggable music provider interface
│   ├── __init__.py         #   Factory: get_provider() reads MUSIC_PROVIDER env
│   ├── base.py             #   Abstract MusicProvider base class
│   ├── youtube.py          #   YouTube provider (ytmusicapi + yt-dlp-host sidecar)
│   └── plex.py             #   Plex provider (python-plexapi)
├── templates/              # HTML templates for web UI
│   ├── base.html           #   Shared layout + styles
│   ├── index.html          #   Home (choose input mode)
│   ├── chat.html           #   AI chat interface
│   ├── text_input.html     #   Paste song list
│   ├── review.html         #   Review shuffled playlist
│   ├── match.html          #   Confirm song matches
│   ├── download.html       #   Download progress
│   ├── finalize.html       #   Finalize playlist (edit, reorder, remove)
│   └── yoto.html           #   Yoto upload
├── yoto_scraper.py         # CLI application
├── playlist_chat.py        # AI chat playlist generator
├── yoto_client.py          # Yoto API client
├── icon_selector.py        # AI-powered card icon selection
├── songs.txt               # Song list (for CLI text mode)
├── Dockerfile              # Docker image
├── docker-compose.yml      # Docker Compose config (includes yt-dlp-host sidecar)
├── .env.example            # Environment variable template
├── requirements.txt        # Python dependencies
└── downloads/              # Downloaded MP3s
```
