# Yoto Music Scraper

Download audio (MP3) from YouTube for a list of songs. Searches YouTube Music for accurate matches, lets you confirm each song, then downloads the audio.

## Prerequisites (Windows)

1. **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
2. **FFmpeg** — Required for audio conversion. Install via one of:
   - `winget install ffmpeg` (Windows Package Manager)
   - Or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

## Setup

```bash
# Clone the repo
git clone <repo-url>
cd yoto-music-scraper

# Create virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### 1. Add your songs

Edit `songs.txt` with one song per line:

```
Bohemian Rhapsody - Queen
Hotel California - Eagles
Yesterday - The Beatles
Blinding Lights - The Weeknd
```

### 2. Run the scraper

```bash
python yoto_scraper.py
```

Options:
- Custom song file: `python yoto_scraper.py my_songs.txt`
- Custom output dir: `python yoto_scraper.py -o "C:\Users\You\Music"`

### 3. Confirm each song

The app searches YouTube Music and shows the top 5 matches for each song. You pick the correct one (or skip/retry with a different search).

### 4. Download

After confirming all songs, audio is downloaded and converted to MP3 (192kbps) into the `downloads/` folder.

## File Structure

```
yoto-music-scraper/
├── yoto_scraper.py    # Main application
├── songs.txt          # Your song list (edit this)
├── requirements.txt   # Python dependencies
├── downloads/         # Downloaded MP3s (created automatically)
└── README.md
```
