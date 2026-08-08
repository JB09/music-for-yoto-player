"""Tests for YotoClient: token handling, auth URLs and file helpers."""

import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

import yoto_client
from yoto_client import YotoClient


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    """Point TOKEN_FILE at a temp path so tests never touch the real one."""
    path = tmp_path / "tokens.json"
    monkeypatch.setattr(yoto_client, "TOKEN_FILE", path)
    return path


@pytest.fixture
def client(token_file):
    return YotoClient(client_id="test-client-id")


class TestContentTypeFor:
    @pytest.mark.parametrize("filename,expected", [
        ("song.mp3", "audio/mpeg"),
        ("song.m4a", "audio/mp4"),
        ("song.aac", "audio/aac"),
        ("song.ogg", "audio/ogg"),
        ("song.wav", "audio/wav"),
        ("song.flac", "audio/flac"),
        ("song.opus", "audio/opus"),
    ])
    def test_known_extensions(self, filename, expected):
        assert YotoClient._content_type_for(filename) == expected

    def test_extension_matching_is_case_insensitive(self):
        assert YotoClient._content_type_for("SONG.FLAC") == "audio/flac"

    def test_unknown_extension_defaults_to_mpeg(self):
        assert YotoClient._content_type_for("song.xyz") == "audio/mpeg"

    def test_full_path_is_handled(self):
        assert YotoClient._content_type_for("/downloads/a - b.wav") == "audio/wav"


class TestTokenPersistence:
    def test_loads_saved_tokens_on_construction(self, token_file):
        token_file.write_text(json.dumps({
            "access_token": "acc", "refresh_token": "ref", "expires_at": 12345,
        }))

        client = YotoClient("cid")

        assert client.access_token == "acc"
        assert client.refresh_token == "ref"
        assert client.expires_at == 12345

    def test_missing_token_file_leaves_client_unauthenticated(self, token_file):
        client = YotoClient("cid")
        assert client.access_token is None
        assert client.expires_at == 0

    def test_corrupt_token_file_is_tolerated(self, token_file):
        token_file.write_text("{not json")
        client = YotoClient("cid")
        assert client.access_token is None

    def test_save_round_trips(self, client, token_file):
        client.access_token = "a"
        client.refresh_token = "r"
        client.expires_at = 999

        client._save_tokens()

        assert json.loads(token_file.read_text()) == {
            "access_token": "a", "refresh_token": "r", "expires_at": 999,
        }


class TestIsAuthenticated:
    def test_true_for_unexpired_token(self, client):
        client.access_token = "acc"
        client.expires_at = time.time() + 3600
        assert client.is_authenticated() is True

    def test_false_with_no_tokens(self, client):
        assert client.is_authenticated() is False

    def test_expired_token_triggers_refresh(self, client, monkeypatch):
        client.access_token = "old"
        client.refresh_token = "ref"
        client.expires_at = time.time() - 1
        calls = []
        monkeypatch.setattr(client, "_refresh", lambda: calls.append(1) or True)

        assert client.is_authenticated() is True
        assert calls == [1]

    def test_expired_token_without_refresh_token_is_false(self, client):
        client.access_token = "old"
        client.expires_at = time.time() - 1
        assert client.is_authenticated() is False


class TestHeaders:
    def test_includes_bearer_token(self, client):
        client.access_token = "acc"
        client.expires_at = time.time() + 3600

        headers = client._headers()

        assert headers["Authorization"] == "Bearer acc"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    def test_refreshes_an_expired_token(self, client, monkeypatch):
        client.access_token = "old"
        client.refresh_token = "ref"
        client.expires_at = time.time() - 1

        def fake_refresh():
            client.access_token = "new"
            client.expires_at = time.time() + 3600
            return True

        monkeypatch.setattr(client, "_refresh", fake_refresh)

        assert client._headers()["Authorization"] == "Bearer new"


class TestGetAuthorizeUrl:
    def test_builds_expected_query_string(self, client):
        url = client.get_authorize_url("https://app.example/callback", "state123")
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        assert url.startswith(f"{yoto_client.AUTH_BASE}/authorize?")
        assert params["response_type"] == ["code"]
        assert params["client_id"] == ["test-client-id"]
        assert params["redirect_uri"] == ["https://app.example/callback"]
        assert params["state"] == ["state123"]
        assert params["scope"] == [yoto_client.SCOPES]
        assert params["audience"] == [yoto_client.AUDIENCE]

    def test_redirect_uri_is_url_encoded(self, client):
        url = client.get_authorize_url("https://app.example/cb?x=1&y=2", "s")
        assert "https%3A%2F%2Fapp.example%2Fcb" in url
        # The nested query must not leak into the outer one as a separate param.
        assert parse_qs(urlparse(url).query)["redirect_uri"] == [
            "https://app.example/cb?x=1&y=2"
        ]


def test_sha256_file_matches_hashlib(client, tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"fake audio bytes" * 1000)

    assert client._sha256_file(str(audio)) == hashlib.sha256(
        audio.read_bytes()
    ).hexdigest()


def test_sha256_file_handles_empty_file(client, tmp_path):
    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")

    assert client._sha256_file(str(empty)) == hashlib.sha256(b"").hexdigest()
