"""Tests for playlist_chat: response parsing and API availability checks."""

import playlist_chat


class TestExtractSongsFromResponse:
    def test_parses_json_fenced_block(self):
        text = (
            "Here you go!\n"
            '```json\n[{"title": "Yellow Submarine", "artist": "The Beatles"}, '
            '{"title": "Octopus\'s Garden", "artist": "The Beatles"}]\n```\n'
            "A nautical playlist."
        )
        songs = playlist_chat.extract_songs_from_response(text)
        assert songs == [
            {"title": "Yellow Submarine", "artist": "The Beatles"},
            {"title": "Octopus's Garden", "artist": "The Beatles"},
        ]

    def test_parses_unlabelled_fence(self):
        text = '```\n[{"title": "Baby Shark", "artist": "Pinkfong"}]\n```'
        assert playlist_chat.extract_songs_from_response(text) == [
            {"title": "Baby Shark", "artist": "Pinkfong"}
        ]

    def test_returns_none_without_a_code_fence(self):
        text = '[{"title": "Baby Shark", "artist": "Pinkfong"}]'
        assert playlist_chat.extract_songs_from_response(text) is None

    def test_returns_none_when_json_is_malformed(self):
        text = '```json\n[{"title": "Broken", "artist":}]\n```'
        assert playlist_chat.extract_songs_from_response(text) is None

    def test_returns_none_when_a_song_is_missing_artist(self):
        text = '```json\n[{"title": "No Artist Here"}]\n```'
        assert playlist_chat.extract_songs_from_response(text) is None

    def test_returns_none_when_fence_has_no_array(self):
        assert playlist_chat.extract_songs_from_response("```json\n{}\n```") is None

    def test_accepts_empty_array(self):
        assert playlist_chat.extract_songs_from_response("```json\n[]\n```") == []

    def test_ignores_prose_around_the_block(self):
        text = (
            "I picked songs with [brackets] in the intro.\n"
            '```json\n[{"title": "Twinkle", "artist": "Trad"}]\n```'
        )
        assert playlist_chat.extract_songs_from_response(text) == [
            {"title": "Twinkle", "artist": "Trad"}
        ]


class TestCheckApiAvailable:
    def test_false_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert playlist_chat.check_api_available() is False

    def test_true_with_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert playlist_chat.check_api_available() is True

    def test_false_when_sdk_missing(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setattr(playlist_chat, "anthropic", None)
        assert playlist_chat.check_api_available() is False


def test_display_playlist_lists_every_song(capsys):
    playlist_chat.display_playlist([
        {"title": "Song A", "artist": "Artist A"},
        {"title": "Song B", "artist": "Artist B"},
    ])
    out = capsys.readouterr().out
    assert "Song A" in out and "Artist A" in out
    assert "Song B" in out and "Artist B" in out
    assert "(2 songs)" in out
