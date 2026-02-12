"""Abstract base class for music providers."""

from abc import ABC, abstractmethod


class MusicProvider(ABC):
    """Interface that all music backends must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'YouTube', 'Plex')."""

    @property
    @abstractmethod
    def supports_preview(self) -> bool:
        """Whether this provider supports in-browser audio preview."""

    @abstractmethod
    def search(self, query: str, num_results: int = 5) -> list[dict]:
        """Search for tracks matching *query*.

        Returns a list of dicts, each containing at minimum:
            trackId  – unique identifier for retrieving the audio later
            title    – track title
            artist   – artist name(s)
            album    – album name (may be empty)
            duration – human-readable duration string (may be empty)
        """

    @abstractmethod
    def get_audio(self, track_id: str, title: str, artist: str,
                  force: bool = False) -> str | None:
        """Retrieve an audio file for the given track.

        Returns the local filesystem path to the audio file, or None on
        failure.  Implementations should cache (skip re-download) unless
        *force* is True.
        """

    def get_preview_url(self, track_id: str) -> str:
        """Return a URL suitable for in-browser preview/embed.

        Only meaningful when *supports_preview* is True.
        """
        return ""
