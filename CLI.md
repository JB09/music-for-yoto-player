# CLI Usage

A command-line interface for downloading YouTube audio and optionally uploading to Yoto MYO cards.

See the main [README](README.md) for setup, Docker, and Yoto API configuration.

---

## AI Chat mode

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

## Text file mode

```bash
python yoto_scraper.py                  # uses songs.txt
python yoto_scraper.py my_songs.txt     # custom file
```

## With Yoto upload

```bash
python yoto_scraper.py --chat --yoto YOUR_CLIENT_ID
python yoto_scraper.py --chat --yoto YOUR_CLIENT_ID --card-name "Bedtime Songs"
```

## All CLI options

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

## Song File Format

One song per line in `songs.txt`. Lines starting with `#` are comments.

```
Bohemian Rhapsody - Queen
Hotel California - Eagles
Yesterday - The Beatles
Blinding Lights - The Weeknd
```

Tip: Adding the artist name improves search accuracy, but just the song title works too.
