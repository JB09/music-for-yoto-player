"""
Yoto API client for uploading audio and creating MYO cards.

Handles OAuth2 device-code authentication, audio upload with transcoding,
and MYO card/playlist creation via the official Yoto Developer API.

API docs: https://yoto.dev/api/
"""

import hashlib
import json
import time
import webbrowser
from pathlib import Path

import requests

AUTH_BASE = "https://login.yotoplay.com"
API_BASE = "https://api.yotoplay.com"
TOKEN_FILE = Path.home() / ".yoto-scraper-tokens.json"

# Scopes needed for MYO upload
SCOPES = "profile offline_access openid"
AUDIENCE = "https://api.yotoplay.com"


class YotoClient:
    """Client for the Yoto Developer API."""

    def __init__(self, client_id: str):
        self.client_id = client_id
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at: float = 0
        self._load_tokens()

    # ── Authentication ──────────────────────────────────────────────

    def _load_tokens(self):
        """Load saved tokens from disk."""
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.expires_at = data.get("expires_at", 0)
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_tokens(self):
        """Persist tokens to disk."""
        TOKEN_FILE.write_text(json.dumps({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }))

    def _headers(self) -> dict:
        """Return authorization headers for API calls."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def is_authenticated(self) -> bool:
        """Check if we have a valid (or refreshable) token."""
        if self.access_token and time.time() < self.expires_at:
            return True
        if self.refresh_token:
            return self._refresh()
        return False

    def authenticate(self) -> bool:
        """Run the OAuth2 device-code flow (interactive, opens browser)."""
        # Step 1: Request device code
        resp = requests.post(f"{AUTH_BASE}/oauth/device/code", json={
            "client_id": self.client_id,
            "scope": SCOPES,
            "audience": AUDIENCE,
        })
        resp.raise_for_status()
        data = resp.json()

        device_code = data["device_code"]
        user_code = data["user_code"]
        verification_url = data.get("verification_uri_complete", data["verification_uri"])
        interval = data.get("interval", 5)
        expires_in = data.get("expires_in", 900)

        # Prompt user to authorize
        print(f"\n  To authorize, visit: {verification_url}")
        print(f"  Your code: {user_code}")
        print(f"  (Attempting to open browser automatically...)")
        webbrowser.open(verification_url)

        # Step 2: Poll for token
        deadline = time.time() + expires_in
        while time.time() < deadline:
            time.sleep(interval)
            resp = requests.post(f"{AUTH_BASE}/oauth/token", json={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.client_id,
                "device_code": device_code,
            })

            if resp.status_code == 200:
                token_data = resp.json()
                self.access_token = token_data["access_token"]
                self.refresh_token = token_data.get("refresh_token")
                self.expires_at = time.time() + token_data.get("expires_in", 86400)
                self._save_tokens()
                print("  Authentication successful!")
                return True

            error = resp.json().get("error", "")
            if error == "authorization_pending":
                print("  Waiting for authorization...", end="\r", flush=True)
                continue
            if error == "slow_down":
                interval += 2
                continue
            if error in ("expired_token", "access_denied"):
                print(f"  Authorization failed: {error}")
                return False

        print("  Authorization timed out.")
        return False

    def _refresh(self) -> bool:
        """Refresh the access token using the stored refresh token."""
        try:
            resp = requests.post(f"{AUTH_BASE}/oauth/token", json={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": self.refresh_token,
            })
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data["access_token"]
            self.refresh_token = data.get("refresh_token", self.refresh_token)
            self.expires_at = time.time() + data.get("expires_in", 86400)
            self._save_tokens()
            return True
        except Exception:
            return False

    def ensure_authenticated(self) -> bool:
        """Make sure we have a valid token, refreshing or re-authing if needed."""
        if self.is_authenticated():
            return True
        print("\n  Yoto authentication required.")
        return self.authenticate()

    # ── Upload ──────────────────────────────────────────────────────

    def _sha256_file(self, filepath: str) -> str:
        """Compute SHA-256 hex digest of a file."""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def get_upload_url(self, sha256: str) -> dict:
        """Request a signed upload URL from Yoto."""
        resp = requests.get(
            f"{API_BASE}/media/transcode/audio/uploadUrl",
            params={"sha256": sha256},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()["upload"]

    def upload_file(self, filepath: str) -> str:
        """Upload an audio file and return the uploadId."""
        sha256 = self._sha256_file(filepath)
        upload_info = self.get_upload_url(sha256)
        upload_id = upload_info["uploadId"]
        upload_url = upload_info.get("uploadUrl")

        if upload_url:
            # File doesn't already exist on Yoto — upload it
            with open(filepath, "rb") as f:
                file_data = f.read()
            resp = requests.put(
                upload_url,
                data=file_data,
                headers={"Content-Type": "audio/mpeg"},
            )
            resp.raise_for_status()

        return upload_id

    def wait_for_transcode(
        self, upload_id: str, max_attempts: int = 60, interval: float = 2.0
    ) -> dict:
        """Poll until transcoding is complete. Returns transcode metadata."""
        for attempt in range(max_attempts):
            resp = requests.get(
                f"{API_BASE}/media/upload/{upload_id}/transcoded",
                params={"loudnorm": "false"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json().get("data", {}).get("transcode", {})

            if data.get("transcodedSha256"):
                return data

            time.sleep(interval)
            if attempt % 5 == 4:
                print(f"    Still transcoding... ({attempt + 1}s)", flush=True)

        raise TimeoutError(f"Transcoding timed out after {max_attempts * interval}s")

    def upload_and_transcode(self, filepath: str) -> dict:
        """Upload a file and wait for transcoding. Returns transcode metadata."""
        filename = Path(filepath).name
        print(f"    Uploading {filename}...", flush=True)
        upload_id = self.upload_file(filepath)
        print(f"    Waiting for transcoding...", flush=True)
        result = self.wait_for_transcode(upload_id)
        print(f"    Transcoded successfully.", flush=True)
        return result

    # ── Card/Playlist Creation ──────────────────────────────────────

    def create_myo_card(self, title: str, tracks: list[dict]) -> dict:
        """
        Create a MYO card with the given tracks.

        Each track dict should have:
            title: str
            transcodedSha256: str
            duration: int (seconds)
            fileSize: int (bytes)
            channels: str ("stereo" or "mono")
            format: str ("aac")
        """
        chapters = []
        for i, track in enumerate(tracks):
            key = f"{i + 1:02d}"
            chapters.append({
                "key": key,
                "title": track["title"],
                "overlayLabel": str(i + 1),
                "tracks": [{
                    "key": "01",
                    "title": track["title"],
                    "trackUrl": f"yoto:#{track['transcodedSha256']}",
                    "duration": track.get("duration", 0),
                    "fileSize": track.get("fileSize", 0),
                    "channels": track.get("channels", "stereo"),
                    "format": track.get("format", "aac"),
                    "type": "audio",
                    "overlayLabel": str(i + 1),
                }],
            })

        total_duration = sum(t.get("duration", 0) for t in tracks)
        total_size = sum(t.get("fileSize", 0) for t in tracks)

        payload = {
            "title": title,
            "content": {
                "chapters": chapters,
                "config": {
                    "resumeTimeout": 0,
                    "playbackType": "default",
                },
            },
            "metadata": {
                "description": f"Created by Yoto Music Scraper ({len(tracks)} tracks)",
                "media": {
                    "duration": total_duration,
                    "fileSize": total_size,
                },
            },
        }

        resp = requests.post(
            f"{API_BASE}/content",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("card", resp.json())

    # ── Utilities ───────────────────────────────────────────────────

    def list_myo_cards(self) -> list[dict]:
        """List the user's existing MYO cards."""
        resp = requests.get(
            f"{API_BASE}/content",
            params={"type": "myo"},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("cards", [])
