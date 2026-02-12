"""
Music Scraper for Yoto - Web UI (Flask).

A step-by-step wizard:
  1. Build playlist via AI chat or paste a song list
  2. Review shuffled/capped list
  3. Confirm YouTube matches for each song
  4. Download MP3s + optional Yoto upload
"""

import json
import os
import random
import secrets
import hashlib
import glob
import threading
import uuid
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, jsonify

import yt_dlp
from ytmusicapi import YTMusic

MAX_SONGS = 12
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "downloads")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

ytmusic = YTMusic()

# In-memory store for background upload jobs keyed by job_id.
# Each entry: {"status": "running"|"done"|"error"|"cancelling", "current": int,
#              "total": int, "current_title": str, "tracks": [], "errors": [],
#              "result": dict|None}
_upload_jobs: dict[str, dict] = {}
_upload_jobs_lock = threading.Lock()


# ── Helpers ─────────────────────────────────────────────────────────


# Words too common/short to be meaningful in filename matching
_STOP_WORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "is",
    "it", "my", "me", "we", "us", "by", "so", "no", "do", "be", "am", "as",
    "if", "up", "he", "she", "i", "oh", "ya", "yo", "ft", "feat", "vs",
    "remix", "mix", "edit", "version", "ver", "pt", "vol",
}


def _significant_words(text: str) -> set[str]:
    """Extract meaningful words (3+ chars, not stop words) from text."""
    import re
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {w for w in words if len(w) >= 3 and w not in _STOP_WORDS}


def _flag_downloaded_results(results: list[dict]):
    """
    Flag search results that match files already in OUTPUT_DIR.

    Sets on each result dict:
      - downloaded: True if an exact filename match exists
      - partial_match: filename string if significant title/artist words
                       match an existing file (but not exact)
    """
    try:
        existing_files = os.listdir(OUTPUT_DIR)
    except FileNotFoundError:
        for r in results:
            r["downloaded"] = False
            r["partial_match"] = ""
        return

    mp3_files = [f for f in existing_files if f.lower().endswith(".mp3")]
    # Pre-compute significant words for each existing file
    file_words = {}
    for f in mp3_files:
        name_no_ext = os.path.splitext(f)[0]
        file_words[f] = _significant_words(name_no_ext)

    for r in results:
        safe = f"{r['artist']} - {r['title']}".replace("/", "-").replace("\\", "-")
        exact_name = f"{safe}.mp3"

        # Check exact match
        if exact_name in existing_files:
            r["downloaded"] = True
            r["partial_match"] = ""
            continue

        r["downloaded"] = False
        r["partial_match"] = ""

        # Check partial match: do significant words from the result overlap
        # well with any existing filename?
        result_words = _significant_words(f"{r['artist']} {r['title']}")
        if len(result_words) < 2:
            continue

        best_match = ""
        best_score = 0
        for f, fw in file_words.items():
            if not fw:
                continue
            overlap = result_words & fw
            # Score: fraction of result words found in filename
            score = len(overlap) / len(result_words)
            if score > best_score and len(overlap) >= 2:
                best_score = score
                best_match = f

        # Require at least 50% word overlap to flag as partial
        if best_score >= 0.5 and best_match:
            r["partial_match"] = best_match


def search_youtube_music(query: str, num_results: int = 5) -> list[dict]:
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


def download_audio(video_id: str, title: str, artist: str,
                    force: bool = False) -> str | None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_filename = f"{artist} - {title}".replace("/", "-").replace("\\", "-")

    # Skip download if the file already exists (unless force re-download)
    mp3_path = os.path.join(OUTPUT_DIR, f"{safe_filename}.mp3")
    if not force and os.path.exists(mp3_path):
        return mp3_path

    outtmpl = os.path.join(OUTPUT_DIR, f"{safe_filename}.%(ext)s")
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
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        mp3_path = os.path.join(OUTPUT_DIR, f"{safe_filename}.mp3")
        if os.path.exists(mp3_path):
            return mp3_path
        matches = glob.glob(os.path.join(OUTPUT_DIR, f"{safe_filename}.*"))
        return matches[0] if matches else None
    except Exception:
        return None


def chat_with_claude(messages: list[dict]) -> str:
    try:
        import anthropic
    except ImportError:
        return "Error: anthropic package not installed."

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY not set."

    system_prompt = (
        f"You are a music playlist curator. The user will describe what kind of playlist "
        f"they want and you will suggest songs.\n\n"
        f"RULES:\n"
        f"- Always suggest exactly {MAX_SONGS} songs unless the user asks for fewer.\n"
        f"- Return songs as a JSON array in a ```json code block, with each entry having "
        f"\"title\" and \"artist\" fields.\n"
        f"- After the JSON block, add a brief friendly summary.\n"
        f"- If the user asks to swap, add, or remove songs, return the FULL updated list.\n"
        f"- Focus on well-known songs easy to find on YouTube.\n"
        f"- If the playlist is for children, prefer kid-friendly content."
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


def extract_songs_from_text(text: str) -> list[dict] | None:
    start = text.find("```json")
    if start == -1:
        start = text.find("```")
    if start == -1:
        return None
    start = text.find("[", start)
    end = text.find("]", start)
    if start == -1 or end == -1:
        return None
    try:
        songs = json.loads(text[start:end + 1])
        if isinstance(songs, list) and all("title" in s and "artist" in s for s in songs):
            return songs
    except json.JSONDecodeError:
        pass
    return None


# ── Routes ──────────────────────────────────────────────────────────


@app.route("/")
def index():
    session.clear()
    return render_template("index.html")


# ── Chat mode ───────────────────────────────────────────────────────


@app.route("/chat")
def chat_page():
    if "chat_messages" not in session:
        session["chat_messages"] = []
        session["chat_songs"] = []
    return render_template(
        "chat.html",
        messages=session["chat_messages"],
        songs=session.get("chat_songs", []),
    )


@app.route("/chat/send", methods=["POST"])
def chat_send():
    user_msg = request.form.get("message", "").strip()
    if not user_msg:
        return redirect(url_for("chat_page"))

    messages = session.get("chat_messages", [])
    messages.append({"role": "user", "content": user_msg})

    # Call Claude
    assistant_text = chat_with_claude(messages)
    messages.append({"role": "assistant", "content": assistant_text})

    # Extract songs if present
    songs = extract_songs_from_text(assistant_text)
    if songs:
        session["chat_songs"] = songs[:MAX_SONGS]

    # Extract summary (text after the JSON block)
    summary = assistant_text
    json_end = assistant_text.rfind("```")
    if json_end != -1:
        summary = assistant_text[json_end + 3:].strip()

    session["chat_messages"] = messages
    return redirect(url_for("chat_page"))


@app.route("/chat/accept", methods=["POST"])
def chat_accept():
    songs = session.get("chat_songs", [])
    if not songs:
        return redirect(url_for("chat_page"))
    song_strings = [f"{s['title']} - {s['artist']}" for s in songs]
    session["raw_songs"] = song_strings
    session["input_mode"] = "chat"
    return redirect(url_for("review"))


# ── Text input mode ─────────────────────────────────────────────────


@app.route("/text", methods=["GET", "POST"])
def text_input():
    if request.method == "POST":
        text = request.form.get("songs", "")
        songs = [
            line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if songs:
            session["raw_songs"] = songs
            session["input_mode"] = "text"
            return redirect(url_for("review"))
    return render_template("text_input.html")


# ── Review shuffled list ────────────────────────────────────────────


@app.route("/review", methods=["GET", "POST"])
def review():
    if request.method == "POST":
        # User confirmed — proceed to matching
        session["match_index"] = 0
        session["confirmed_songs"] = []
        return redirect(url_for("match_song"))

    songs = session.get("raw_songs", [])
    if not songs:
        return redirect(url_for("index"))

    # Determine cap based on input mode: paste allows up to 100, chat caps at 12
    input_mode = session.get("input_mode", "chat")
    cap = MAX_TRACKS_PER_CARD if input_mode == "text" else MAX_SONGS

    # Shuffle and cap
    if "shuffled" not in session:
        random.shuffle(songs)
        songs = songs[:cap]
        session["raw_songs"] = songs
        session["shuffled"] = True

    return render_template("review.html", songs=songs, max_songs=cap,
                           input_mode=input_mode)


@app.route("/review/reorder", methods=["POST"])
def review_reorder():
    """Accept a reordered (and possibly reduced) song list from the review page."""
    data = request.get_json(silent=True)
    if data and "songs" in data:
        cap = MAX_TRACKS_PER_CARD if session.get("input_mode") == "text" else MAX_SONGS
        session["raw_songs"] = data["songs"][:cap]
    return jsonify({"ok": True})


@app.route("/review/reshuffle", methods=["POST"])
def reshuffle():
    session.pop("shuffled", None)
    return redirect(url_for("review"))


# ── YouTube matching (one song at a time) ───────────────────────────


def _finish_rematch():
    """Restore session state after a rematch and redirect to results."""
    session["raw_songs"] = session.pop("_saved_raw_songs", [])
    session["match_index"] = session.pop("_saved_match_index", 0)
    session["confirmed_songs"] = session.pop("_saved_confirmed_songs", [])
    session.pop("rematch_query", None)
    session.pop("rematch_index", None)
    return redirect(url_for("download_results"))


@app.route("/match", methods=["GET", "POST"])
def match_song():
    songs = session.get("raw_songs", [])
    idx = session.get("match_index", 0)
    confirmed = session.get("confirmed_songs", [])
    is_rematch = "rematch_index" in session

    if idx >= len(songs):
        if is_rematch:
            return _finish_rematch()
        return redirect(url_for("download_page"))

    query = request.args.get("q", songs[idx])

    if request.method == "POST":
        action = request.form.get("action")

        if action == "select":
            selected = json.loads(request.form.get("song_data", "{}"))

            if is_rematch:
                # Download immediately and update the results entry
                force = selected.get("force_download", False)
                filepath = download_audio(
                    selected["videoId"], selected["title"], selected["artist"],
                    force=force,
                )
                rematch_idx = session["rematch_index"]
                results = session.get("download_results", [])
                if 0 <= rematch_idx < len(results):
                    results[rematch_idx] = {
                        "title": selected["title"],
                        "artist": selected["artist"],
                        "success": filepath is not None,
                        "filepath": filepath or "",
                    }
                    session["download_results"] = results
                return _finish_rematch()

            confirmed.append(selected)
            session["confirmed_songs"] = confirmed
            session["match_index"] = idx + 1
            return redirect(url_for("match_song"))

        elif action == "skip":
            if is_rematch:
                return _finish_rematch()
            session["match_index"] = idx + 1
            return redirect(url_for("match_song"))

        elif action == "retry":
            new_query = request.form.get("new_query", "").strip()
            if new_query:
                return redirect(url_for("match_song", q=new_query))

    results = search_youtube_music(query)

    # Flag results that already have a downloaded file in OUTPUT_DIR
    _flag_downloaded_results(results)

    # Sort so downloaded/matched files come first (stable sort preserves relevance order)
    # Exact matches first, then partial, then unmatched
    results.sort(key=lambda r: (0 if r["downloaded"] else 1 if r.get("partial_match") else 2))

    return render_template(
        "match.html",
        query=query,
        original_query=songs[idx],
        results=results,
        current=idx + 1,
        total=len(songs),
        confirmed_count=len(confirmed),
        is_rematch=is_rematch,
    )


# ── Download ────────────────────────────────────────────────────────


@app.route("/download")
def download_page():
    confirmed = session.get("confirmed_songs", [])
    if not confirmed:
        return redirect(url_for("index"))
    return render_template("download.html", songs=confirmed)


@app.route("/download/start", methods=["POST"])
def download_start():
    confirmed = session.get("confirmed_songs", [])
    results = []

    for song in confirmed:
        force = song.get("force_download", False)
        filepath = download_audio(song["videoId"], song["title"], song["artist"],
                                  force=force)
        results.append({
            "title": song["title"],
            "artist": song["artist"],
            "success": filepath is not None,
            "filepath": filepath or "",
        })

    session["download_results"] = results
    return jsonify(results)


@app.route("/download/results")
def download_results():
    from yoto_client import YotoClient

    results = session.get("download_results", [])
    confirmed = session.get("confirmed_songs", [])
    client_id = os.environ.get("YOTO_CLIENT_ID", "")
    yoto_available = bool(client_id)

    yoto_authenticated = False
    if yoto_available:
        client = YotoClient(client_id)
        yoto_authenticated = client.is_authenticated()

    return render_template(
        "results.html",
        results=results,
        total=len(results),
        success_count=sum(1 for r in results if r["success"]),
        yoto_available=yoto_available,
        yoto_authenticated=yoto_authenticated,
    )


# ── Track rename ───────────────────────────────────────────────────


@app.route("/track/rename", methods=["POST"])
def track_rename():
    """Rename a downloaded track's artist/title and update the file on disk."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data"}), 400

    idx = data.get("index")
    new_title = data.get("title", "").strip()
    new_artist = data.get("artist", "").strip()

    results = session.get("download_results", [])
    if idx is None or idx < 0 or idx >= len(results):
        return jsonify({"error": "Invalid index"}), 400

    track = results[idx]
    if not track.get("success") or not track.get("filepath"):
        return jsonify({"error": "Track has no file"}), 400

    if not new_title or not new_artist:
        return jsonify({"error": "Title and artist are required"}), 400

    old_path = track["filepath"]
    new_safe = f"{new_artist} - {new_title}".replace("/", "-").replace("\\", "-")
    new_path = os.path.join(OUTPUT_DIR, f"{new_safe}.mp3")

    # Rename the file if path changed and old file exists
    if old_path != new_path and os.path.exists(old_path):
        try:
            os.rename(old_path, new_path)
        except OSError as e:
            return jsonify({"error": f"Rename failed: {e}"}), 500

    track["title"] = new_title
    track["artist"] = new_artist
    track["filepath"] = new_path
    session["download_results"] = results
    return jsonify({"ok": True, "filepath": new_path})


@app.route("/track/reorder", methods=["POST"])
def track_reorder():
    """Accept a reordered list of track indices for the results page."""
    data = request.get_json(silent=True)
    if not data or "order" not in data:
        return jsonify({"error": "No data"}), 400

    results = session.get("download_results", [])
    order = data["order"]  # list of original indices

    # Validate and reorder
    if sorted(order) != list(range(len(results))):
        return jsonify({"error": "Invalid order"}), 400

    session["download_results"] = [results[i] for i in order]
    return jsonify({"ok": True})


@app.route("/track/delete", methods=["POST"])
def track_delete():
    """Remove a track from the results list (does not delete the file)."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data"}), 400

    idx = data.get("index")
    results = session.get("download_results", [])
    if idx is None or idx < 0 or idx >= len(results):
        return jsonify({"error": "Invalid index"}), 400

    results.pop(idx)
    session["download_results"] = results
    return jsonify({"ok": True, "count": sum(1 for r in results if r["success"])})


@app.route("/track/rematch", methods=["POST"])
def track_rematch():
    """Set up re-match mode for a single track, then redirect to /match."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data"}), 400

    idx = data.get("index")
    results = session.get("download_results", [])
    if idx is None or idx < 0 or idx >= len(results):
        return jsonify({"error": "Invalid index"}), 400

    track = results[idx]
    query = f"{track['title']} - {track['artist']}"

    # Save rematch state
    session["rematch_index"] = idx
    session["rematch_query"] = query

    # Set up the match machinery for one song
    session["_saved_raw_songs"] = session.get("raw_songs", [])
    session["_saved_match_index"] = session.get("match_index", 0)
    session["_saved_confirmed_songs"] = session.get("confirmed_songs", [])

    session["raw_songs"] = [query]
    session["match_index"] = 0
    session["confirmed_songs"] = []

    return jsonify({"ok": True, "redirect": url_for("match_song")})


# ── Yoto Authentication (Authorization Code flow) ──────────────────


def _yoto_redirect_uri():
    """Build the OAuth callback URL based on the current request."""
    base_url = os.environ.get("YOTO_REDIRECT_URI")
    if base_url:
        return base_url.rstrip("/") + "/yoto/callback"
    return request.host_url.rstrip("/") + "/yoto/callback"


@app.route("/yoto/auth")
def yoto_auth():
    """Start the Yoto OAuth Authorization Code flow."""
    from yoto_client import YotoClient

    client_id = os.environ.get("YOTO_CLIENT_ID", "")
    if not client_id:
        return "YOTO_CLIENT_ID not configured", 400

    state = secrets.token_urlsafe(32)
    session["yoto_oauth_state"] = state

    client = YotoClient(client_id)
    authorize_url = client.get_authorize_url(_yoto_redirect_uri(), state)
    return redirect(authorize_url)


@app.route("/yoto/callback")
def yoto_callback():
    """Handle the OAuth callback from Yoto after user authorizes."""
    from yoto_client import YotoClient

    error = request.args.get("error")
    if error:
        error_desc = request.args.get("error_description", error)
        return render_template("results.html",
                               results=session.get("download_results", []),
                               total=len(session.get("confirmed_songs", [])),
                               success_count=sum(1 for r in session.get("download_results", []) if r["success"]),
                               yoto_available=True,
                               yoto_authenticated=False,
                               yoto_auth_error=f"Authorization failed: {error_desc}")

    code = request.args.get("code", "")
    state = request.args.get("state", "")

    # Verify state to prevent CSRF
    if state != session.pop("yoto_oauth_state", None):
        return "Invalid OAuth state — possible CSRF attack.", 403

    client_id = os.environ.get("YOTO_CLIENT_ID", "")
    client = YotoClient(client_id)

    try:
        client.exchange_code(code, _yoto_redirect_uri())
    except Exception as e:
        return f"Token exchange failed: {e}", 500

    # Redirect back to the results page (now authenticated)
    return redirect(url_for("download_results"))


# ── Yoto Cards List ────────────────────────────────────────────────

MAX_TRACKS_PER_CARD = 100


@app.route("/yoto/cards")
def yoto_cards():
    """Return the user's existing MYO cards as JSON for the dropdown."""
    from yoto_client import YotoClient

    client_id = os.environ.get("YOTO_CLIENT_ID", "")
    if not client_id:
        return jsonify({"error": "YOTO_CLIENT_ID not configured"}), 400

    client = YotoClient(client_id)
    if not client.is_authenticated():
        return jsonify({"error": "Not authenticated"}), 401

    try:
        cards = client.list_myo_cards()
        result = []
        for c in cards:
            card_id = c.get("cardId", c.get("_id", ""))
            title = c.get("title", "Untitled")
            # Chapter count from the list endpoint (may be summary only)
            chapters = c.get("content", {}).get("chapters", [])
            result.append({
                "cardId": card_id,
                "title": title,
                "trackCount": len(chapters),
            })
        return jsonify({"cards": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Icon Preview ───────────────────────────────────────────────────


@app.route("/yoto/icon/preview", methods=["POST"])
def yoto_icon_preview():
    """Generate or select an icon and return it as a base64 data URL for preview."""
    from yoto_client import YotoClient

    client_id = os.environ.get("YOTO_CLIENT_ID", "")
    if not client_id:
        return jsonify({"error": "YOTO_CLIENT_ID not configured"}), 400

    client = YotoClient(client_id)
    if not client.is_authenticated():
        return jsonify({"error": "Not authenticated"}), 401

    mode = request.form.get("mode", "generate")
    card_name = request.form.get("card_name", "My Playlist")
    keywords = request.form.get("keywords", "").strip()

    results = session.get("download_results", [])
    successful = [r for r in results if r["success"]]
    song_titles = [f"{s['title']} - {s['artist']}" for s in successful]

    if keywords:
        card_name = f"{card_name} ({keywords})"

    if mode == "generate":
        import base64
        from icon_selector import generate_custom_icon
        try:
            icon_bytes = generate_custom_icon(song_titles, card_name)
            if icon_bytes:
                b64 = base64.b64encode(icon_bytes).decode("ascii")
                return jsonify({
                    "preview": f"data:image/png;base64,{b64}",
                    "mode": "generate",
                })
            else:
                return jsonify({"error": "Icon generation failed. Try again or add keywords."}), 500
        except Exception as e:
            return jsonify({"error": f"Icon generation failed: {e}"}), 500
    else:
        # mode == "public" — pick from public icons and return the URL
        from icon_selector import select_public_icon
        try:
            public_icons = client.get_public_icons()
            if not public_icons:
                return jsonify({"error": "No public icons available"}), 500
            chosen = select_public_icon(public_icons, song_titles, card_name)
            if chosen:
                return jsonify({
                    "preview": chosen.get("url", ""),
                    "mode": "public",
                    "iconId": chosen.get("mediaId") or chosen.get("_id", ""),
                    "reason": chosen.get("_selection_reason", ""),
                })
            else:
                return jsonify({"error": "Could not select a matching icon"}), 500
        except Exception as e:
            return jsonify({"error": f"Icon selection failed: {e}"}), 500


@app.route("/yoto/icon/upload", methods=["POST"])
def yoto_icon_upload():
    """Upload a previewed generated icon to Yoto and return the mediaId."""
    from yoto_client import YotoClient
    import base64

    client_id = os.environ.get("YOTO_CLIENT_ID", "")
    if not client_id:
        return jsonify({"error": "YOTO_CLIENT_ID not configured"}), 400

    client = YotoClient(client_id)
    if not client.is_authenticated():
        return jsonify({"error": "Not authenticated"}), 401

    data_url = request.form.get("icon_data_url", "")
    if not data_url.startswith("data:image/png;base64,"):
        return jsonify({"error": "Invalid icon data"}), 400

    b64 = data_url.split(",", 1)[1]
    icon_bytes = base64.b64decode(b64)

    try:
        result = client.upload_custom_icon(icon_bytes, filename="playlist-icon.png")
        media_id = result.get("mediaId") or result.get("_id", "")
        return jsonify({"iconMediaId": media_id})
    except Exception as e:
        return jsonify({"error": f"Icon upload failed: {e}"}), 500


# ── Yoto Upload (background worker) ────────────────────────────────


def _run_upload_job(job_id: str, successful: list[dict], card_name: str,
                    icon_mode: str, client_id: str,
                    existing_card_id: str | None = None,
                    confirmed_icon_id: str | None = None):
    """Background thread that uploads tracks to Yoto and creates/updates a card."""
    from yoto_client import YotoClient

    job = _upload_jobs[job_id]
    client = YotoClient(client_id)

    # If adding to an existing card, fetch it first to get existing tracks
    existing_icon_id = None
    existing_tracks = []
    if existing_card_id:
        try:
            job["current_title"] = "Loading existing card..."
            card_data = client.get_card(existing_card_id)
            # Capture the existing card's icon so new tracks get it too
            for ch in card_data.get("content", {}).get("chapters", []):
                display = ch.get("display", {})
                icon_ref = display.get("icon16x16", "")
                if icon_ref.startswith("yoto:#"):
                    existing_icon_id = icon_ref.replace("yoto:#", "")
                    break
            existing_chapters = card_data.get("content", {}).get("chapters", [])
            for ch in existing_chapters:
                ch_tracks = ch.get("tracks", [])
                if ch_tracks:
                    t = ch_tracks[0]
                    track_url = t.get("trackUrl", "")
                    sha = track_url.replace("yoto:#", "") if track_url.startswith("yoto:#") else ""
                    existing_tracks.append({
                        "title": ch.get("title", t.get("title", "")),
                        "transcodedSha256": sha,
                        "duration": t.get("duration", 0),
                        "fileSize": t.get("fileSize", 0),
                        "channels": t.get("channels", "stereo"),
                        "format": t.get("format", "aac"),
                    })
            # Check capacity
            available = MAX_TRACKS_PER_CARD - len(existing_tracks)
            if available <= 0:
                job["status"] = "error"
                job["result"] = {
                    "error": f"Card already has {len(existing_tracks)} tracks "
                             f"(max {MAX_TRACKS_PER_CARD}). No room for new tracks.",
                }
                return
            if len(successful) > available:
                job["status"] = "error"
                job["result"] = {
                    "error": f"Card has {len(existing_tracks)} tracks with room for "
                             f"{available} more, but you're trying to add "
                             f"{len(successful)}. Please reduce your playlist.",
                }
                return
        except Exception as e:
            job["status"] = "error"
            job["result"] = {"error": f"Failed to load existing card: {e}"}
            return

    tracks = []
    errors = []
    cancelled = False
    for i, song in enumerate(successful):
        # Check if user requested cancellation before starting next track
        if job["status"] == "cancelling":
            cancelled = True
            break
        job["current"] = i + 1
        job["current_title"] = song["title"]
        try:
            data = client.upload_and_transcode(song["filepath"])
            tracks.append({
                "title": f"{song['title']} - {song['artist']}",
                "transcodedSha256": data["transcodedSha256"],
                "duration": data.get("duration", 0),
                "fileSize": data.get("fileSize", 0),
                "channels": data.get("channels", "stereo"),
                "format": data.get("format", "aac"),
            })
        except Exception as e:
            errors.append(f"{song['title']}: {e}")
            # Also check for cancellation after a failed upload
            if job["status"] == "cancelling":
                cancelled = True
                break

    job["errors"] = errors

    if not tracks:
        job["status"] = "error"
        job["result"] = {"error": "All uploads failed", "details": errors}
        return

    if cancelled:
        job["current_title"] = "Finishing with completed tracks..."

    if existing_card_id:
        # Merge existing + new tracks and update the card, preserving the icon
        all_tracks = existing_tracks + tracks
        job["current_title"] = "Updating existing card..."
        try:
            card = client.update_myo_card(
                existing_card_id, card_name, all_tracks,
                icon_media_id=existing_icon_id,
            )
            card_id = card.get("cardId", card.get("_id", "unknown"))
            job["status"] = "done"
            job["result"] = {
                "success": True,
                "cardId": card_id,
                "tracksUploaded": len(tracks),
                "totalTracks": len(all_tracks),
                "iconSet": existing_icon_id is not None,
                "errors": errors,
                "updated": True,
                "cancelled": cancelled,
                "totalRequested": len(successful),
            }
        except Exception as e:
            job["status"] = "error"
            job["result"] = {"error": f"Card update failed: {e}"}
        return

    # Use pre-confirmed icon if provided, otherwise select/generate one
    icon_media_id = confirmed_icon_id
    if not icon_media_id:
        job["current_title"] = "Selecting card icon..."
        try:
            from icon_selector import select_icon_for_card
            song_titles = [t["title"] for t in tracks]
            prefer_generate = icon_mode == "generate"
            icon_media_id = select_icon_for_card(
                client, song_titles, card_name, prefer_generate=prefer_generate,
            )
        except Exception as e:
            errors.append(f"Icon selection failed: {e}")

    job["current_title"] = "Creating MYO card..."

    try:
        card = client.create_myo_card(card_name, tracks, icon_media_id=icon_media_id)
        card_id = card.get("cardId", card.get("_id", "unknown"))
        job["status"] = "done"
        job["result"] = {
            "success": True,
            "cardId": card_id,
            "tracksUploaded": len(tracks),
            "iconSet": icon_media_id is not None,
            "errors": errors,
            "cancelled": cancelled,
            "totalRequested": len(successful),
        }
    except Exception as e:
        job["status"] = "error"
        job["result"] = {"error": f"Card creation failed: {e}"}


@app.route("/yoto/upload", methods=["POST"])
def yoto_upload():
    from yoto_client import YotoClient

    client_id = os.environ.get("YOTO_CLIENT_ID", "")
    if not client_id:
        return jsonify({"error": "YOTO_CLIENT_ID not configured"}), 400

    card_name = request.form.get("card_name", "My Playlist")
    icon_mode = request.form.get("icon_mode", "public")
    existing_card_id = request.form.get("existing_card_id", "").strip() or None
    confirmed_icon_id = request.form.get("confirmed_icon_id", "").strip() or None
    results = session.get("download_results", [])
    successful = [r for r in results if r["success"]]

    if not successful:
        return jsonify({"error": "No downloaded files to upload"}), 400

    client = YotoClient(client_id)
    if not client.is_authenticated():
        return jsonify({
            "error": "Not authenticated with Yoto. Please connect your Yoto account first.",
            "needs_auth": True,
        }), 401

    # Create a background job
    job_id = uuid.uuid4().hex[:12]
    _upload_jobs[job_id] = {
        "status": "running",
        "current": 0,
        "total": len(successful),
        "current_title": "",
        "tracks": [],
        "errors": [],
        "result": None,
    }

    thread = threading.Thread(
        target=_run_upload_job,
        args=(job_id, successful, card_name, icon_mode, client_id,
              existing_card_id, confirmed_icon_id),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/yoto/upload/status")
def yoto_upload_status():
    job_id = request.args.get("job_id", "")
    job = _upload_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job ID"}), 404

    resp = {
        "status": job["status"],
        "current": job["current"],
        "total": job["total"],
        "current_title": job["current_title"],
    }

    # Report "cancelling" as still running so the client keeps polling
    if job["status"] == "cancelling":
        resp["cancelling"] = True

    if job["status"] in ("done", "error"):
        resp["result"] = job["result"]
        # Clean up finished job
        _upload_jobs.pop(job_id, None)

    return jsonify(resp)


@app.route("/yoto/upload/cancel", methods=["POST"])
def yoto_upload_cancel():
    job_id = request.form.get("job_id") or request.json.get("job_id", "")
    job = _upload_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job ID"}), 404
    if job["status"] == "running":
        job["status"] = "cancelling"
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
