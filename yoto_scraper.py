"""
Music Scraper for Yoto - Download audio from YouTube and upload to Yoto MYO cards.

Usage:
    python yoto_scraper.py --chat                     # Build playlist via AI chat
    python yoto_scraper.py                            # Uses songs.txt
    python yoto_scraper.py --chat --yoto CLIENT_ID    # Chat + upload to Yoto
    python yoto_scraper.py songs.txt --no-shuffle     # File input, keep order
"""

import argparse
import glob
import os
import random
import sys
from pathlib import Path

import yt_dlp
from ytmusicapi import YTMusic

MAX_SONGS = 12


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


def apply_limits(songs: list[str], shuffle: bool, max_songs: int) -> list[str]:
    """Shuffle and cap the song list."""
    if shuffle:
        random.shuffle(songs)
    if len(songs) > max_songs:
        print(f"  Trimming to {max_songs} songs (from {len(songs)}).")
        songs = songs[:max_songs]
    return songs


def display_final_list(songs: list[str]):
    """Show the final song list before proceeding."""
    print(f"\n  Final playlist ({len(songs)} songs):")
    print(f"  {'─'*50}")
    for i, s in enumerate(songs, 1):
        print(f"  {i:2d}. {s}")
    print()


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


def download_audio(video_id: str, title: str, artist: str, output_dir: str) -> str | None:
    """Download audio from YouTube using yt-dlp. Returns the output filepath or None."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    safe_filename = f"{artist} - {title}".replace("/", "-").replace("\\", "-")
    outtmpl = os.path.join(output_dir, f"{safe_filename}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_progress_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        # Find the output file (yt-dlp replaces %(ext)s with the final extension)
        mp3_path = os.path.join(output_dir, f"{safe_filename}.mp3")
        if os.path.exists(mp3_path):
            return mp3_path
        # Fallback: glob for the file
        matches = glob.glob(os.path.join(output_dir, f"{safe_filename}.*"))
        return matches[0] if matches else None
    except Exception as e:
        print(f"  Error downloading: {e}")
        return None


def _progress_hook(d):
    """Show download progress."""
    if d["status"] == "downloading":
        pct = d.get("_percent_str", "?%").strip()
        print(f"\r  Downloading... {pct}", end="", flush=True)
    elif d["status"] == "finished":
        print(f"\r  Download complete. Converting to MP3...", flush=True)


def upload_to_yoto(downloaded_songs: list[dict], client_id: str, card_name: str):
    """Upload downloaded songs to Yoto and create a MYO card."""
    from yoto_client import YotoClient

    client = YotoClient(client_id)
    if not client.ensure_authenticated():
        print("  Failed to authenticate with Yoto. Skipping upload.")
        return

    print(f"\n  Uploading {len(downloaded_songs)} song(s) to Yoto...")
    tracks = []
    for i, song in enumerate(downloaded_songs, 1):
        filepath = song["filepath"]
        label = f"{song['title']} - {song['artist']}"
        print(f"\n  [{i}/{len(downloaded_songs)}] {label}")

        try:
            transcode_data = client.upload_and_transcode(filepath)
            tracks.append({
                "title": label,
                "transcodedSha256": transcode_data["transcodedSha256"],
                "duration": transcode_data.get("duration", 0),
                "fileSize": transcode_data.get("fileSize", 0),
                "channels": transcode_data.get("channels", "stereo"),
                "format": transcode_data.get("format", "aac"),
            })
        except Exception as e:
            print(f"    Failed to upload: {e}")

    if not tracks:
        print("\n  No tracks were uploaded successfully.")
        return

    print(f"\n  Creating MYO card: \"{card_name}\" ({len(tracks)} tracks)...")
    try:
        card = client.create_myo_card(card_name, tracks)
        card_id = card.get("cardId", card.get("_id", "unknown"))
        print(f"  MYO card created! Card ID: {card_id}")
        print(f"\n  Next step: Open the Yoto app and link this playlist to a")
        print(f"  physical MYO card (tap with NFC or insert into player).")
    except Exception as e:
        print(f"  Failed to create MYO card: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Download audio from YouTube and optionally upload to Yoto MYO cards."
    )

    # Input source (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--chat",
        action="store_true",
        help="Build playlist interactively via AI chat (requires ANTHROPIC_API_KEY)",
    )
    input_group.add_argument(
        "songfile",
        nargs="?",
        default=None,
        help="Path to text file with song names (default: songs.txt)",
    )

    # Output and limits
    parser.add_argument(
        "-o", "--output",
        default="downloads",
        help="Output directory for downloaded files (default: downloads/)",
    )
    parser.add_argument(
        "--max-songs",
        type=int,
        default=MAX_SONGS,
        help=f"Maximum number of songs to process (default: {MAX_SONGS})",
    )
    parser.add_argument(
        "--no-shuffle",
        action="store_true",
        help="Keep songs in original order (default: randomize)",
    )

    # Yoto integration
    parser.add_argument(
        "--yoto",
        metavar="CLIENT_ID",
        help="Yoto API client ID — enables upload to Yoto MYO card after download",
    )
    parser.add_argument(
        "--card-name",
        default=None,
        help="Name for the Yoto MYO card/playlist (default: prompt at runtime)",
    )
    args = parser.parse_args()

    # ── Get song list ──────────────────────────────────────────────
    if args.chat:
        from playlist_chat import chat_playlist
        songs = chat_playlist()
        if not songs:
            print("\nNo songs selected. Exiting.")
            sys.exit(0)
    else:
        songfile = args.songfile or "songs.txt"
        songs = load_songs(songfile)
        print(f"Loaded {len(songs)} song(s) from '{songfile}'")

    # ── Shuffle and cap ────────────────────────────────────────────
    shuffle = not args.no_shuffle
    songs = apply_limits(songs, shuffle=shuffle, max_songs=args.max_songs)
    display_final_list(songs)

    proceed = input("  Proceed with these songs? [Y/n]: ").strip().lower()
    if proceed and proceed != "y":
        print("  Cancelled.")
        sys.exit(0)

    # Create output directory
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    # Initialize YouTube Music search
    ytmusic = YTMusic()

    # ── Phase 1: Search and confirm all songs ──────────────────────
    print("\n--- PHASE 1: Search & Confirm Songs on YouTube ---")
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

    # ── Phase 2: Download confirmed songs ──────────────────────────
    print(f"\n--- PHASE 2: Downloading {len(confirmed)} song(s) ---")
    downloaded = []
    for i, song in enumerate(confirmed, 1):
        print(f"\n[{i}/{len(confirmed)}] {song['title']} - {song['artist']}")
        filepath = download_audio(song["videoId"], song["title"], song["artist"], output_dir)
        if filepath:
            downloaded.append({
                "title": song["title"],
                "artist": song["artist"],
                "filepath": filepath,
            })
            print(f"  Saved to: {filepath}")
        else:
            print(f"  FAILED")

    print(f"\n{'='*60}")
    print(f"  {len(downloaded)}/{len(confirmed)} songs downloaded to '{output_dir}/'")
    print(f"{'='*60}")

    # ── Phase 3: Upload to Yoto (if enabled) ───────────────────────
    if args.yoto and downloaded:
        print(f"\n--- PHASE 3: Upload to Yoto ---")
        card_name = args.card_name
        if not card_name:
            card_name = input("\n  Enter a name for the MYO card/playlist: ").strip()
            if not card_name:
                card_name = "My Playlist"
        upload_to_yoto(downloaded, args.yoto, card_name)
    elif args.yoto and not downloaded:
        print("\n  No songs downloaded — skipping Yoto upload.")

    print("\nDone!")


if __name__ == "__main__":
    main()
