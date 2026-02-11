# Yoto Music Scraper

Download audio (MP3) from YouTube and optionally upload directly to a Yoto Player MYO card — all from the command line.

**3-phase workflow:**
1. **Search & Confirm** — searches YouTube Music, you pick the right match for each song
2. **Download** — downloads audio as MP3 via yt-dlp
3. **Upload to Yoto** _(optional)_ — uploads to Yoto and creates a MYO card playlist

## Prerequisites (Windows)

1. **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
2. **FFmpeg** — Required for audio conversion
   - `winget install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

## Setup

```bash
git clone <repo-url>
cd yoto-music-scraper

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

## Usage

### Download only (no Yoto)

```bash
# Edit songs.txt with one song per line, then:
python yoto_scraper.py

# Custom song file and output directory:
python yoto_scraper.py my_songs.txt -o "C:\Users\You\Music"
```

### Download + Upload to Yoto MYO Card

```bash
python yoto_scraper.py --yoto YOUR_CLIENT_ID
python yoto_scraper.py --yoto YOUR_CLIENT_ID --card-name "Road Trip Mix"
```

On first run, it opens your browser to authenticate with Yoto. Tokens are saved to `~/.yoto-scraper-tokens.json` so you only need to log in once.

## Setting Up Yoto API Access

1. Go to [yoto.dev/get-started](https://yoto.dev/get-started/start-here/) and register for a developer account
2. Obtain your **Client ID** from the Yoto Developers portal
3. Pass it via the `--yoto` flag

The app uses the [OAuth2 Device Code flow](https://yoto.dev/authentication/auth/) — on first run it will display a URL and code. Open the URL, enter the code, and log in with your Yoto account.

## Song File Format

One song per line in `songs.txt`. Lines starting with `#` are comments.

```
Bohemian Rhapsody - Queen
Hotel California - Eagles
Yesterday - The Beatles
Blinding Lights - The Weeknd
```

Tip: Adding the artist name improves search accuracy, but just the song title works too.

## How It Works

```
songs.txt
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
yoto-music-scraper/
├── yoto_scraper.py    # Main CLI application (phases 1-3)
├── yoto_client.py     # Yoto API client (auth, upload, card creation)
├── songs.txt          # Your song list (edit this)
├── requirements.txt   # Python dependencies
├── downloads/         # Downloaded MP3s (created automatically)
└── README.md
```

## Note on the Physical Card Step

Everything is automated except the final step: linking the playlist to a physical MYO card. This requires either:
- **NFC tap** via the Yoto mobile app (hold card to phone)
- **Insert card** into a connected Yoto Player

This is a hardware interaction that can't be automated via software.
