"""
Yoto Music Scraper - Download audio from YouTube for a list of songs.

Usage:
    python yoto_scraper.py                    # Uses songs.txt in current directory
    python yoto_scraper.py my_songs.txt       # Uses a custom song list file
    python yoto_scraper.py -o C:\Music        # Specify output directory
"""

import argparse
import os
import sys
from pathlib import Path

import yt_dlp
from ytmusicapi import YTMusic


def load_songs(filepath: str) -> list[str]:
    """Load song names from a text file (one per line, ignoring comments and blanks)."""
    path = Path(filepath)
    if not path.exists():
        print(f"Error: Song file '{filepath}' not found.")
        sys.exit(1)

    songs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            songs.append(line)

    if not songs:
        print(f"Error: No songs found in '{filepath}'. Add one song per line.")
        sys.exit(1)

    return songs


def search_youtube(ytmusic: YTMusic, query: str, num_results: int = 5) -> list[dict]:
    """Search YouTube Music for a song and return top results."""
    results = ytmusic.search(query, filter="songs", limit=num_results)
    parsed = []
    for r in results:
        artists = ", ".join(a["name"] for a in r.get("artists", []))
        parsed.append({
            "title": r.get("title", "Unknown"),
            "artist": artists or "Unknown",
            "album": r.get("album", {}).get("name", "") if r.get("album") else "",
            "duration": r.get("duration", ""),
            "videoId": r.get("videoId", ""),
        })
    return parsed


def confirm_song(query: str, results: list[dict]) -> dict | None:
    """Display search results and let the user pick the correct one."""
    print(f"\n{'='*60}")
    print(f"  Search: \"{query}\"")
    print(f"{'='*60}")

    if not results:
        print("  No results found.")
        choice = input("  [s]kip or [r]etry with different search? ").strip().lower()
        if choice == "r":
            new_query = input("  Enter new search term: ").strip()
            return {"retry": new_query} if new_query else None
        return None

    for i, r in enumerate(results, 1):
        album_str = f" [{r['album']}]" if r["album"] else ""
        duration_str = f" ({r['duration']})" if r["duration"] else ""
        print(f"  {i}. {r['title']} - {r['artist']}{album_str}{duration_str}")

    print(f"  0. Skip this song")
    print(f"  r. Retry with a different search term")

    while True:
        choice = input(f"\n  Select [1-{len(results)}/0/r]: ").strip().lower()
        if choice == "0":
            return None
        if choice == "r":
            new_query = input("  Enter new search term: ").strip()
            return {"retry": new_query} if new_query else None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                selected = results[idx]
                print(f"  -> Selected: {selected['title']} - {selected['artist']}")
                return selected
        except ValueError:
            pass
        print(f"  Invalid choice. Enter 1-{len(results)}, 0, or r.")


def download_audio(video_id: str, title: str, artist: str, output_dir: str) -> bool:
    """Download audio from YouTube using yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    safe_filename = f"{artist} - {title}".replace("/", "-").replace("\\", "-")

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "outtmpl": os.path.join(output_dir, f"{safe_filename}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_progress_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        print(f"  Error downloading: {e}")
        return False


def _progress_hook(d):
    """Show download progress."""
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "?%").strip()
        print(f"\r  Downloading... {pct}", end="", flush=True)
    elif d["status"] == "finished":
        print(f"\r  Download complete. Converting to MP3...", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Download audio from YouTube for a list of songs."
    )
    parser.add_argument(
        "songfile",
        nargs="?",
        default="songs.txt",
        help="Path to text file with song names (default: songs.txt)",
    )
    parser.add_argument(
        "-o", "--output",
        default="downloads",
        help="Output directory for downloaded files (default: downloads/)",
    )
    args = parser.parse_args()

    # Load songs
    songs = load_songs(args.songfile)
    print(f"Loaded {len(songs)} song(s) from '{args.songfile}'")

    # Create output directory
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    # Initialize YouTube Music search
    ytmusic = YTMusic()

    # Phase 1: Search and confirm all songs
    print("\n--- PHASE 1: Search & Confirm Songs ---")
    confirmed = []
    for song_query in songs:
        query = song_query
        while True:
            results = search_youtube(ytmusic, query)
            selection = confirm_song(query, results)
            if selection is None:
                print(f"  Skipped: {song_query}")
                break
            if isinstance(selection, dict) and "retry" in selection:
                query = selection["retry"]
                continue
            confirmed.append(selection)
            break

    if not confirmed:
        print("\nNo songs confirmed for download. Exiting.")
        sys.exit(0)

    # Phase 2: Download confirmed songs
    print(f"\n--- PHASE 2: Downloading {len(confirmed)} song(s) ---")
    success_count = 0
    for i, song in enumerate(confirmed, 1):
        print(f"\n[{i}/{len(confirmed)}] {song['title']} - {song['artist']}")
        if download_audio(song["videoId"], song["title"], song["artist"], output_dir):
            success_count += 1
            print(f"  Saved to: {output_dir}/")
        else:
            print(f"  FAILED")

    # Summary
    print(f"\n{'='*60}")
    print(f"  Done! {success_count}/{len(confirmed)} songs downloaded to '{output_dir}/'")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
