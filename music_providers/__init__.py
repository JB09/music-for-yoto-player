"""
Music provider abstraction layer.

Supports multiple backends for searching and retrieving audio files:
- youtube: YouTube Music search + yt-dlp-host sidecar for audio download
- plex: Plex Media Server library search + direct file retrieval
"""

import os

from music_providers.base import MusicProvider


def get_provider(output_dir: str = "downloads") -> MusicProvider:
    """Create a MusicProvider based on MUSIC_PROVIDER env var.

    Supported values: "youtube" (default), "plex".
    """
    provider_type = os.environ.get("MUSIC_PROVIDER", "youtube").lower()

    if provider_type == "youtube":
        from music_providers.youtube import YouTubeProvider
        return YouTubeProvider(
            output_dir=output_dir,
            download_service_url=os.environ.get("DOWNLOAD_SERVICE_URL", ""),
            download_api_key=os.environ.get("DOWNLOAD_API_KEY", ""),
        )

    elif provider_type == "plex":
        from music_providers.plex import PlexProvider
        return PlexProvider(
            output_dir=output_dir,
            plex_url=os.environ.get("PLEX_URL", ""),
            plex_token=os.environ.get("PLEX_TOKEN", ""),
            plex_music_library=os.environ.get("PLEX_MUSIC_LIBRARY", "Music"),
        )

    else:
        raise ValueError(
            f"Unknown MUSIC_PROVIDER: '{provider_type}'. "
            "Supported values: youtube, plex"
        )
