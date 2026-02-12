"""YouTube Music provider — search via ytmusicapi, download via yt-dlp-host sidecar."""

import glob
import os
import time

import requests
from ytmusicapi import YTMusic

from music_providers.base import MusicProvider


class YouTubeProvider(MusicProvider):
    """Search YouTube Music and download audio via an external yt-dlp-host service."""

    def __init__(self, output_dir: str = "downloads",
                 download_service_url: str = "",
                 download_api_key: str = ""):
        self._output_dir = output_dir
        self._service_url = download_service_url.rstrip("/")
        self._api_key = download_api_key
        self._ytmusic = YTMusic()

    @property
    def name(self) -> str:
        return "YouTube"

    @property
    def supports_preview(self) -> bool:
        return True

    def search(self, query: str, num_results: int = 5) -> list[dict]:
        results = self._ytmusic.search(query, filter="songs", limit=num_results)
        parsed = []
        for r in results:
            artists = ", ".join(a["name"] for a in r.get("artists", []))
            parsed.append({
                "trackId": r.get("videoId", ""),
                "title": r.get("title", "Unknown"),
                "artist": artists or "Unknown",
                "album": r.get("album", {}).get("name", "") if r.get("album") else "",
                "duration": r.get("duration", ""),
            })
        return parsed

    def get_audio(self, track_id: str, title: str, artist: str,
                  force: bool = False) -> str | None:
        os.makedirs(self._output_dir, exist_ok=True)
        safe_filename = f"{artist} - {title}".replace("/", "-").replace("\\", "-")
        mp3_path = os.path.join(self._output_dir, f"{safe_filename}.mp3")

        if not force and os.path.exists(mp3_path):
            return mp3_path

        if self._service_url:
            return self._download_via_service(track_id, safe_filename)
        return self._download_via_library(track_id, safe_filename)

    def get_preview_url(self, track_id: str) -> str:
        return f"https://www.youtube-nocookie.com/embed/{track_id}?autoplay=1"

    # ── Private helpers ─────────────────────────────────────────────

    def _download_via_service(self, track_id: str, safe_filename: str) -> str | None:
        """Download audio via the yt-dlp-host REST API sidecar."""
        url = f"https://www.youtube.com/watch?v={track_id}"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        try:
            resp = requests.post(
                f"{self._service_url}/get_audio",
                json={
                    "url": url,
                    "audio_format": "bestaudio",
                    "output_format": "mp3",
                },
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            task_id = resp.json().get("task_id")
            if not task_id:
                return None
        except Exception:
            return None

        # Poll for completion (max ~5 minutes)
        file_path = None
        for _ in range(60):
            time.sleep(5)
            try:
                status_resp = requests.get(
                    f"{self._service_url}/status/{task_id}",
                    headers={"X-API-Key": self._api_key} if self._api_key else {},
                    timeout=15,
                )
                status_resp.raise_for_status()
                data = status_resp.json()
            except Exception:
                continue

            if data.get("status") == "completed":
                file_path = data.get("file")
                break
            elif data.get("status") == "error":
                return None

        if not file_path:
            return None

        # Retrieve the file from the sidecar
        try:
            dl_resp = requests.get(
                f"{self._service_url}/files/{file_path}",
                headers={"X-API-Key": self._api_key} if self._api_key else {},
                timeout=120,
                stream=True,
            )
            dl_resp.raise_for_status()
            dest = os.path.join(self._output_dir, f"{safe_filename}.mp3")
            with open(dest, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return dest
        except Exception:
            return None

    def _download_via_library(self, track_id: str, safe_filename: str) -> str | None:
        """Fallback: download directly using the yt-dlp Python library."""
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError(
                "yt-dlp library is not installed and DOWNLOAD_SERVICE_URL is not set. "
                "Either pip install yt-dlp or configure the yt-dlp-host sidecar."
            )

        url = f"https://www.youtube.com/watch?v={track_id}"
        outtmpl = os.path.join(self._output_dir, f"{safe_filename}.%(ext)s")
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
                ydl.download([url])
            mp3_path = os.path.join(self._output_dir, f"{safe_filename}.mp3")
            if os.path.exists(mp3_path):
                return mp3_path
            matches = glob.glob(os.path.join(self._output_dir, f"{safe_filename}.*"))
            return matches[0] if matches else None
        except Exception:
            return None
