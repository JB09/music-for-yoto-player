# Yoto Music Scraper

Download audio (MP3) from YouTube and optionally upload directly to a Yoto Player MYO card — all from the command line.

**Two ways to build your playlist:**
- **AI Chat** (`--chat`) — describe what you want in natural language and Claude generates the song list
- **Text file** — traditional `songs.txt` with one song per line

**Then the 3-phase pipeline runs:**
1. **Shuffle & Cap** — randomizes the list and limits to 12 songs (configurable)
2. **Search & Confirm** — searches YouTube Music, you pick the right match for each
3. **Download** — downloads audio as MP3 via yt-dlp
4. **Upload to Yoto** _(optional)_ — uploads to Yoto and creates a MYO card playlist

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

### For AI Chat mode

Set your Anthropic API key:
```bash
set ANTHROPIC_API_KEY=sk-ant-...
```
Get a key at [console.anthropic.com](https://console.anthropic.com/).

## Usage

### AI Chat mode (recommended)

```bash
python yoto_scraper.py --chat
```

Describe what you want in natural language:
```
You: Relaxing bedtime songs for a 3-year-old
You: Swap out track 4 for something by Raffi
You: done
```

The chat is multi-turn — refine the list until you're happy, then type `done`.

### Text file mode

```bash
# Edit songs.txt with one song per line, then:
python yoto_scraper.py

# Custom song file:
python yoto_scraper.py my_songs.txt
```

### With Yoto upload

```bash
python yoto_scraper.py --chat --yoto YOUR_CLIENT_ID
python yoto_scraper.py --chat --yoto YOUR_CLIENT_ID --card-name "Bedtime Songs"
```

### All options

```
python yoto_scraper.py [songfile] [options]

Input (mutually exclusive):
  --chat              Build playlist via AI chat (requires ANTHROPIC_API_KEY)
  songfile            Path to text file (default: songs.txt)

Options:
  -o, --output DIR    Output directory (default: downloads/)
  --max-songs N       Max songs to process (default: 12)
  --no-shuffle        Keep songs in original order (default: randomize)
  --yoto CLIENT_ID    Enable Yoto MYO card upload
  --card-name NAME    Name for the Yoto card (default: prompt at runtime)
```

## Shuffle & Song Limit

By default, the song list is **randomized** and **capped at 12 songs**. This is designed for Yoto MYO cards where you typically want a manageable playlist for kids.

- Override the cap: `--max-songs 8` or `--max-songs 20`
- Disable shuffle: `--no-shuffle`
- The final list is always shown for confirmation before downloading

## Setting Up Yoto API Access

1. Go to [yoto.dev/get-started](https://yoto.dev/get-started/start-here/) and register for a developer account
2. Obtain your **Client ID** from the Yoto Developers portal
3. Pass it via the `--yoto` flag

The app uses the [OAuth2 Device Code flow](https://yoto.dev/authentication/auth/) — on first run it will display a URL and code. Open the URL, enter the code, and log in with your Yoto account. Tokens are saved to `~/.yoto-scraper-tokens.json` for reuse.

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
--chat  OR  songs.txt
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
├── yoto_scraper.py    # Main CLI application
├── playlist_chat.py   # AI chat playlist generator (Anthropic/Claude)
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
