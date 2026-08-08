"""Tests for the provider factory and the YouTube provider's parsing/caching."""

import os

import pytest

import music_providers
from music_providers import youtube as youtube_module


class FakeYTMusic:
    """Stub for ytmusicapi.YTMusic — records queries, returns canned results."""

    def __init__(self, *args, **kwargs):
        self.queries = []
        self.results = []

    def search(self, query, filter=None, limit=5):  # noqa: A002 - mirrors the real API
        self.queries.append((query, filter, limit))
        return self.results[:limit]


@pytest.fixture
def provider(monkeypatch, tmp_path):
    """A YouTubeProvider whose YTMusic client is a stub."""
    monkeypatch.setattr(youtube_module, "YTMusic", FakeYTMusic)
    return youtube_module.YouTubeProvider(
        output_dir=str(tmp_path),
        download_service_url="http://ytdlp.invalid:5000",
        download_api_key="key",
    )


class TestGetProvider:
    def test_defaults_to_youtube(self, monkeypatch):
        monkeypatch.delenv("MUSIC_PROVIDER", raising=False)
        monkeypatch.setattr(youtube_module, "YTMusic", FakeYTMusic)

        assert music_providers.get_provider().name == "YouTube"

    def test_value_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MUSIC_PROVIDER", "YouTube")
        monkeypatch.setattr(youtube_module, "YTMusic", FakeYTMusic)

        assert music_providers.get_provider().name == "YouTube"

    def test_plex_provider(self, monkeypatch):
        monkeypatch.setenv("MUSIC_PROVIDER", "plex")
        monkeypatch.setenv("PLEX_URL", "http://plex.invalid:32400/")

        provider = music_providers.get_provider()

        assert provider.name == "Plex"
        assert provider.supports_preview is False

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("MUSIC_PROVIDER", "spotify")

        with pytest.raises(ValueError, match="Unknown MUSIC_PROVIDER"):
            music_providers.get_provider()


class TestYouTubeSearch:
    def test_parses_results(self, provider):
        provider._ytmusic.results = [{
            "videoId": "abc123",
            "title": "Yellow Submarine",
            "artists": [{"name": "The Beatles"}],
            "album": {"name": "Revolver"},
            "duration": "2:40",
        }]

        assert provider.search("yellow submarine") == [{
            "trackId": "abc123",
            "title": "Yellow Submarine",
            "artist": "The Beatles",
            "album": "Revolver",
            "duration": "2:40",
        }]

    def test_joins_multiple_artists(self, provider):
        provider._ytmusic.results = [{
            "videoId": "x", "title": "Duet",
            "artists": [{"name": "A"}, {"name": "B"}],
        }]

        assert provider.search("duet")[0]["artist"] == "A, B"

    def test_missing_fields_fall_back_to_defaults(self, provider):
        provider._ytmusic.results = [{}]

        assert provider.search("nothing") == [{
            "trackId": "", "title": "Unknown", "artist": "Unknown",
            "album": "", "duration": "",
        }]

    def test_null_album_yields_empty_string(self, provider):
        provider._ytmusic.results = [{"videoId": "x", "title": "T", "album": None}]

        assert provider.search("t")[0]["album"] == ""

    def test_passes_song_filter_and_limit(self, provider):
        provider.search("query", num_results=3)

        assert provider._ytmusic.queries == [("query", "songs", 3)]

    def test_limit_is_respected(self, provider):
        provider._ytmusic.results = [
            {"videoId": str(i), "title": f"T{i}"} for i in range(10)
        ]

        assert len(provider.search("many", num_results=4)) == 4


class TestYouTubeGetAudio:
    def test_returns_cached_file_without_downloading(self, provider, tmp_path, monkeypatch):
        existing = tmp_path / "The Beatles - Yellow Submarine.mp3"
        existing.write_bytes(b"audio")
        monkeypatch.setattr(
            provider, "_download_via_service",
            lambda *a, **k: pytest.fail("should not download a cached track"),
        )

        result = provider.get_audio("abc", "Yellow Submarine", "The Beatles")

        assert result == str(existing)

    def test_force_redownloads_even_when_cached(self, provider, tmp_path, monkeypatch):
        (tmp_path / "The Beatles - Yellow Submarine.mp3").write_bytes(b"audio")
        calls = []
        monkeypatch.setattr(
            provider, "_download_via_service",
            lambda track_id, name: calls.append((track_id, name)) or "downloaded",
        )

        result = provider.get_audio(
            "abc", "Yellow Submarine", "The Beatles", force=True
        )

        assert result == "downloaded"
        assert calls == [("abc", "The Beatles - Yellow Submarine")]

    def test_sanitises_slashes_in_the_filename(self, provider, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            provider, "_download_via_service",
            lambda track_id, name: captured.setdefault("name", name),
        )

        provider.get_audio("id", "Rock/Roll", "AC\\DC")

        assert captured["name"] == "AC-DC - Rock-Roll"

    def test_creates_the_output_directory(self, monkeypatch, tmp_path):
        monkeypatch.setattr(youtube_module, "YTMusic", FakeYTMusic)
        target = tmp_path / "nested" / "downloads"
        provider = youtube_module.YouTubeProvider(
            output_dir=str(target), download_service_url="http://svc.invalid"
        )
        monkeypatch.setattr(provider, "_download_via_service", lambda *a: None)

        provider.get_audio("id", "T", "A")

        assert os.path.isdir(target)

    def test_raises_when_no_download_service_configured(self, monkeypatch, tmp_path):
        monkeypatch.setattr(youtube_module, "YTMusic", FakeYTMusic)
        provider = youtube_module.YouTubeProvider(output_dir=str(tmp_path))

        with pytest.raises(RuntimeError, match="DOWNLOAD_SERVICE_URL"):
            provider.get_audio("id", "T", "A")

    def test_service_url_trailing_slash_is_stripped(self, monkeypatch, tmp_path):
        monkeypatch.setattr(youtube_module, "YTMusic", FakeYTMusic)
        provider = youtube_module.YouTubeProvider(
            output_dir=str(tmp_path), download_service_url="http://svc.invalid:5000/"
        )

        assert provider._service_url == "http://svc.invalid:5000"


def test_preview_url_uses_nocookie_embed(provider):
    assert provider.get_preview_url("abc123") == (
        "https://www.youtube-nocookie.com/embed/abc123?autoplay=1"
    )


def test_provider_metadata(provider):
    assert provider.name == "YouTube"
    assert provider.supports_preview is True
