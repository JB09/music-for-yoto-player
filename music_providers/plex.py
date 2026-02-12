"""Plex Media Server provider — search library and retrieve audio files."""

import os
import shutil

from music_providers.base import MusicProvider


class PlexProvider(MusicProvider):
    """Search a Plex music library and copy/download audio files locally."""

    def __init__(self, output_dir: str = "downloads",
                 plex_url: str = "",
                 plex_token: str = "",
                 plex_music_library: str = "Music"):
        self._output_dir = output_dir
        self._plex_url = plex_url.rstrip("/")
        self._plex_token = plex_token
        self._library_name = plex_music_library
        self._server = None
        self._music = None

    @property
    def name(self) -> str:
        return "Plex"

    @property
    def supports_preview(self) -> bool:
        return False

    def search(self, query: str, num_results: int = 5) -> list[dict]:
        music = self._get_library()
        tracks = music.search(query, libtype="track", limit=num_results)

        parsed = []
        for t in tracks:
            duration_ms = t.duration or 0
            mins, secs = divmod(duration_ms // 1000, 60)
            duration_str = f"{mins}:{secs:02d}" if duration_ms else ""

            parsed.append({
                "trackId": str(t.ratingKey),
                "title": t.title or "Unknown",
                "artist": t.grandparentTitle or t.originalTitle or "Unknown",
                "album": t.parentTitle or "",
                "duration": duration_str,
            })
        return parsed

    def get_audio(self, track_id: str, title: str, artist: str,
                  force: bool = False) -> str | None:
        os.makedirs(self._output_dir, exist_ok=True)
        safe_filename = f"{artist} - {title}".replace("/", "-").replace("\\", "-")
        mp3_path = os.path.join(self._output_dir, f"{safe_filename}.mp3")

        if not force and os.path.exists(mp3_path):
            return mp3_path

        music = self._get_library()

        try:
            track = music.fetchItem(int(track_id))
        except Exception:
            return None

        # Determine the original file format
        container = None
        for media in track.media:
            for part in media.parts:
                container = part.container
                break

        if container and container.lower() == "mp3":
            # Already MP3 — try direct file copy if accessible, else download
            return self._retrieve_file(track, safe_filename, transcode=False)
        else:
            # Non-MP3 (FLAC, AAC, etc.) — ask Plex to transcode to MP3
            return self._retrieve_file(track, safe_filename, transcode=True)

    # ── Private helpers ─────────────────────────────────────────────

    def _get_library(self):
        """Lazy-connect to Plex and return the music library section."""
        if self._music is not None:
            return self._music

        try:
            from plexapi.server import PlexServer
        except ImportError:
            raise RuntimeError(
                "python-plexapi is not installed. "
                "pip install PlexAPI or set MUSIC_PROVIDER=youtube"
            )

        if not self._plex_url or not self._plex_token:
            raise RuntimeError(
                "PLEX_URL and PLEX_TOKEN must be set when using the Plex provider."
            )

        self._server = PlexServer(self._plex_url, self._plex_token)
        self._music = self._server.library.section(self._library_name)
        return self._music

    def _retrieve_file(self, track, safe_filename: str,
                       transcode: bool = False) -> str | None:
        """Download a track from Plex to the output directory."""
        dest = os.path.join(self._output_dir, f"{safe_filename}.mp3")

        try:
            if not transcode:
                # Try local file path first (works if Plex storage is mounted)
                for media in track.media:
                    for part in media.parts:
                        if part.file and os.path.exists(part.file):
                            shutil.copy2(part.file, dest)
                            return dest

            # Download via Plex HTTP (with transcoding if needed)
            import requests
            if transcode:
                stream_url = track.getStreamURL(audioCodec="mp3")
            else:
                # Direct download of original file
                key = track.media[0].parts[0].key
                stream_url = f"{self._plex_url}{key}?X-Plex-Token={self._plex_token}"

            resp = requests.get(stream_url, timeout=120, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return dest

        except Exception:
            return None
