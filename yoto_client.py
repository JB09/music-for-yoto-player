"""
Yoto API client for uploading audio and creating MYO cards.

Handles OAuth2 authentication (device-code flow for CLI, authorization-code
flow for web), audio upload with transcoding, and MYO card/playlist creation
via the official Yoto Developer API.

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
        """Return authorization headers for API calls.

        Automatically refreshes the access token if it has expired.
        """
        if self.access_token and time.time() >= self.expires_at and self.refresh_token:
            self._refresh()
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

    # ── Authorization Code Flow (for web apps) ───────────────────────

    def get_authorize_url(self, redirect_uri: str, state: str) -> str:
        """
        Build the authorization URL for the Authorization Code flow.

        The user's browser should be redirected to this URL. After login,
        Yoto redirects back to redirect_uri with ?code=...&state=...
        """
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "audience": AUDIENCE,
            "state": state,
        }
        return f"{AUTH_BASE}/authorize?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> bool:
        """
        Exchange an authorization code for access + refresh tokens.

        Called from the OAuth callback handler after the user authorizes.
        Returns True on success.
        """
        resp = requests.post(f"{AUTH_BASE}/oauth/token", json={
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
        })
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        self.expires_at = time.time() + data.get("expires_in", 86400)
        self._save_tokens()
        return True

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

    @staticmethod
    def _content_type_for(filepath: str) -> str:
        """Return the MIME type for an audio file based on extension."""
        ext = Path(filepath).suffix.lower()
        return {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".opus": "audio/opus",
        }.get(ext, "audio/mpeg")

    def upload_file(self, filepath: str) -> str:
        """Upload an audio file and return the uploadId."""
        sha256 = self._sha256_file(filepath)
        upload_info = self.get_upload_url(sha256)
        upload_id = upload_info["uploadId"]
        upload_url = upload_info.get("uploadUrl")

        if upload_url:
            # File doesn't already exist on Yoto — upload it
            filename = Path(filepath).name
            content_type = self._content_type_for(filepath)
            with open(filepath, "rb") as f:
                file_data = f.read()
            resp = requests.put(
                upload_url,
                data=file_data,
                headers={
                    "Content-Type": content_type,
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )
            resp.raise_for_status()

        return upload_id

    def wait_for_transcode(
        self, upload_id: str, max_attempts: int = 300, interval: float = 2.0
    ) -> dict:
        """Poll until transcoding is complete. Returns transcode metadata.

        Default timeout: 300 attempts × 2s = 10 minutes.
        """
        for attempt in range(max_attempts):
            resp = requests.get(
                f"{API_BASE}/media/upload/{upload_id}/transcoded",
                params={"loudnorm": "false"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            transcode = resp.json().get("transcode", {})

            if transcode.get("transcodedSha256"):
                return transcode

            time.sleep(interval)
            elapsed = int((attempt + 1) * interval)
            if attempt % 5 == 4:
                print(f"    Still transcoding... ({elapsed}s)", flush=True)

        raise TimeoutError(
            f"Transcoding timed out after {int(max_attempts * interval)}s"
        )

    def upload_and_transcode(self, filepath: str) -> dict:
        """Upload a file and wait for transcoding. Returns transcode metadata."""
        filename = Path(filepath).name
        print(f"    Uploading {filename}...", flush=True)
        upload_id = self.upload_file(filepath)
        print(f"    Waiting for transcoding...", flush=True)
        result = self.wait_for_transcode(upload_id)
        print(f"    Transcoded successfully.", flush=True)
        return result

    def batch_upload_and_transcode(
        self,
        songs: list[dict],
        on_progress=None,
        cancel_check=None,
        max_transcode_time: int = 600,
    ) -> tuple[list[dict], list[str]]:
        """Upload all files first, then poll all transcodes in parallel.

        This is much faster than sequential upload+transcode because Yoto
        transcodes files concurrently on their servers.

        Args:
            songs: list of dicts with 'filepath', 'title', 'artist' keys.
            on_progress: optional callback(phase, current, total, title) for UI updates.
            cancel_check: optional callable returning True if user cancelled.
            max_transcode_time: max seconds to wait for all transcoding (default 10min).

        Returns:
            (tracks, errors) — tracks is a list of transcode result dicts,
            errors is a list of error message strings.
        """
        tracks = []
        errors = []
        upload_ids = []  # (upload_id, song) pairs for transcode polling

        # Phase 1: Upload all files (fast — just S3 PUTs)
        for i, song in enumerate(songs):
            if cancel_check and cancel_check():
                break
            filepath = song["filepath"]
            label = f"{song['title']} - {song['artist']}"
            if on_progress:
                on_progress("uploading", i + 1, len(songs), song["title"])
            print(f"    Uploading {Path(filepath).name}...", flush=True)
            try:
                upload_id = self.upload_file(filepath)
                upload_ids.append((upload_id, song))
            except Exception as e:
                errors.append(f"{label}: upload failed — {e}")

        if not upload_ids:
            return tracks, errors

        # Phase 2: Poll all transcodes together
        if on_progress:
            on_progress("transcoding", 0, len(upload_ids), None)
        print(f"    Waiting for {len(upload_ids)} track(s) to transcode...", flush=True)

        pending = {uid: song for uid, song in upload_ids}
        poll_interval = 5.0
        elapsed = 0.0

        while pending and elapsed < max_transcode_time:
            # Sleep in short increments so cancel is responsive
            for _ in range(int(poll_interval)):
                if cancel_check and cancel_check():
                    # Immediately return whatever tracks are already done
                    print(f"    Cancelled — returning {len(tracks)} completed track(s).", flush=True)
                    return tracks, errors
                time.sleep(1.0)
            elapsed += poll_interval

            # Check all pending transcodes
            done_ids = []
            for upload_id, song in list(pending.items()):
                try:
                    resp = requests.get(
                        f"{API_BASE}/media/upload/{upload_id}/transcoded",
                        params={"loudnorm": "false"},
                        headers=self._headers(),
                    )
                    resp.raise_for_status()
                    transcode = resp.json().get("transcode", {})

                    if transcode.get("transcodedSha256"):
                        label = f"{song['title']} - {song['artist']}"
                        info = transcode.get("transcodedInfo", {})
                        tracks.append({
                            "title": label,
                            "transcodedSha256": transcode["transcodedSha256"],
                            "duration": info.get("duration", 0),
                            "fileSize": info.get("fileSize", 0),
                            "channels": info.get("channels", "stereo"),
                            "format": info.get("format", "aac"),
                        })
                        done_ids.append(upload_id)
                        print(f"    Transcoded: {song['title']}", flush=True)
                except Exception as e:
                    label = f"{song['title']} - {song['artist']}"
                    errors.append(f"{label}: transcode check failed — {e}")
                    done_ids.append(upload_id)

            for uid in done_ids:
                del pending[uid]

            if pending and on_progress:
                completed = len(upload_ids) - len(pending)
                on_progress("transcoding", completed, len(upload_ids), None)

            if pending and int(elapsed) % 30 == 0:
                print(
                    f"    Still transcoding {len(pending)} track(s)... ({int(elapsed)}s)",
                    flush=True,
                )

        # Any remaining are timeouts
        for upload_id, song in pending.items():
            label = f"{song['title']} - {song['artist']}"
            errors.append(f"{label}: transcoding timed out after {int(max_transcode_time)}s")

        return tracks, errors

    # ── Card/Playlist Creation ──────────────────────────────────────

    def create_myo_card(self, title: str, tracks: list[dict],
                        icon_media_id: str | None = None,
                        cover_image_url: str | None = None) -> dict:
        """
        Create a MYO card with the given tracks.

        Each track dict should have:
            title: str
            transcodedSha256: str
            duration: int (seconds)
            fileSize: int (bytes)
            channels: str ("stereo" or "mono")
            format: str ("aac")

        icon_media_id: optional Yoto icon mediaId (used as yoto:#<mediaId>)
        """
        icon_ref = f"yoto:#{icon_media_id}" if icon_media_id else None

        chapters = []
        for i, track in enumerate(tracks):
            key = f"{i + 1:02d}"
            chapter = {
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
            }
            if icon_ref:
                chapter["display"] = {"icon16x16": icon_ref}
            chapters.append(chapter)

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
                "description": f"Created by Music Scraper for Yoto ({len(tracks)} tracks)",
                "media": {
                    "duration": total_duration,
                    "fileSize": total_size,
                },
            },
        }

        if cover_image_url:
            payload["cover"] = {"imageL": cover_image_url}

        resp = requests.post(
            f"{API_BASE}/content",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("card", resp.json())

    # ── Icons ────────────────────────────────────────────────────────

    def get_public_icons(self) -> list[dict]:
        """Fetch all public/shared display icons from Yoto."""
        resp = requests.get(
            f"{API_BASE}/media/displayIcons/user/yoto",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("displayIcons", [])

    def upload_custom_icon(self, image_data: bytes, filename: str = "icon.png",
                           auto_convert: bool = True) -> dict:
        """
        Upload a custom 16x16 icon to Yoto.

        Args:
            image_data: Raw PNG image bytes (16x16 px recommended).
            filename: Filename for the upload.
            auto_convert: If True, Yoto resizes/converts to 16x16 PNG automatically.

        Returns:
            dict with 'mediaId', 'url', etc.
        """
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "image/png",
        }
        resp = requests.post(
            f"{API_BASE}/media/displayIcons/user/me/upload",
            params={"autoConvert": str(auto_convert).lower(), "filename": filename},
            data=image_data,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json().get("displayIcon", resp.json())

    def upload_cover_image(self, image_data: bytes, content_type: str = "image/jpeg",
                           auto_convert: bool = True) -> dict:
        """Upload a cover image for a MYO card.

        Args:
            image_data: Raw image bytes (JPEG or PNG).
            content_type: MIME type of the image.
            auto_convert: If True, Yoto resizes to appropriate cover dimensions.

        Returns:
            dict with 'mediaId', 'mediaUrl', etc. from the coverImage object.
        """
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": content_type,
        }
        resp = requests.post(
            f"{API_BASE}/media/coverImage/user/me/upload",
            params={"autoconvert": str(auto_convert).lower(), "coverType": "default"},
            data=image_data,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json().get("coverImage", resp.json())

    def update_myo_card(self, card_id: str, title: str, tracks: list[dict],
                        icon_media_id: str | None = None,
                        cover_image_url: str | None = None) -> dict:
        """
        Update an existing MYO card by posting with its cardId.

        Uses the same POST /content endpoint but includes cardId to update.
        """
        icon_ref = f"yoto:#{icon_media_id}" if icon_media_id else None

        chapters = []
        for i, track in enumerate(tracks):
            key = f"{i + 1:02d}"
            chapter = {
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
            }
            if icon_ref:
                chapter["display"] = {"icon16x16": icon_ref}
            chapters.append(chapter)

        total_duration = sum(t.get("duration", 0) for t in tracks)
        total_size = sum(t.get("fileSize", 0) for t in tracks)

        payload = {
            "cardId": card_id,
            "title": title,
            "content": {
                "chapters": chapters,
                "config": {
                    "resumeTimeout": 0,
                    "playbackType": "default",
                },
            },
            "metadata": {
                "description": f"Created by Music Scraper for Yoto ({len(tracks)} tracks)",
                "media": {
                    "duration": total_duration,
                    "fileSize": total_size,
                },
            },
        }

        if cover_image_url:
            payload["cover"] = {"imageL": cover_image_url}

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

    def get_card(self, card_id: str) -> dict:
        """Get full card details including chapters."""
        resp = requests.get(
            f"{API_BASE}/content/{card_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("card", resp.json())
