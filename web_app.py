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
# Each entry: {"status": "running"|"done"|"error", "current": int,
#              "total": int, "current_title": str, "tracks": [], "errors": [],
#              "result": dict|None}
_upload_jobs: dict[str, dict] = {}
_upload_jobs_lock = threading.Lock()


# ── Helpers ─────────────────────────────────────────────────────────


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


def download_audio(video_id: str, title: str, artist: str) -> str | None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_filename = f"{artist} - {title}".replace("/", "-").replace("\\", "-")
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

    # Shuffle and cap
    if "shuffled" not in session:
        random.shuffle(songs)
        songs = songs[:MAX_SONGS]
        session["raw_songs"] = songs
        session["shuffled"] = True

    return render_template("review.html", songs=songs, max_songs=MAX_SONGS)


@app.route("/review/reshuffle", methods=["POST"])
def reshuffle():
    session.pop("shuffled", None)
    return redirect(url_for("review"))


# ── YouTube matching (one song at a time) ───────────────────────────


@app.route("/match", methods=["GET", "POST"])
def match_song():
    songs = session.get("raw_songs", [])
    idx = session.get("match_index", 0)
    confirmed = session.get("confirmed_songs", [])

    if idx >= len(songs):
        return redirect(url_for("download_page"))

    query = request.args.get("q", songs[idx])

    if request.method == "POST":
        action = request.form.get("action")

        if action == "select":
            selected = json.loads(request.form.get("song_data", "{}"))
            confirmed.append(selected)
            session["confirmed_songs"] = confirmed
            session["match_index"] = idx + 1
            return redirect(url_for("match_song"))

        elif action == "skip":
            session["match_index"] = idx + 1
            return redirect(url_for("match_song"))

        elif action == "retry":
            new_query = request.form.get("new_query", "").strip()
            if new_query:
                return redirect(url_for("match_song", q=new_query))

    results = search_youtube_music(query)
    return render_template(
        "match.html",
        query=query,
        original_query=songs[idx],
        results=results,
        current=idx + 1,
        total=len(songs),
        confirmed_count=len(confirmed),
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
        filepath = download_audio(song["videoId"], song["title"], song["artist"])
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
        total=len(confirmed),
        success_count=sum(1 for r in results if r["success"]),
        yoto_available=yoto_available,
        yoto_authenticated=yoto_authenticated,
    )


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


# ── Yoto Upload (background worker) ────────────────────────────────


def _run_upload_job(job_id: str, successful: list[dict], card_name: str,
                    icon_mode: str, client_id: str):
    """Background thread that uploads tracks to Yoto and creates a card."""
    from yoto_client import YotoClient

    job = _upload_jobs[job_id]
    client = YotoClient(client_id)

    tracks = []
    errors = []
    for i, song in enumerate(successful):
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

    job["errors"] = errors

    if not tracks:
        job["status"] = "error"
        job["result"] = {"error": "All uploads failed", "details": errors}
        return

    job["current_title"] = "Selecting card icon..."

    # Select an icon for the card via AI
    icon_media_id = None
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
        args=(job_id, successful, card_name, icon_mode, client_id),
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

    if job["status"] in ("done", "error"):
        resp["result"] = job["result"]
        # Clean up finished job
        _upload_jobs.pop(job_id, None)

    return jsonify(resp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
