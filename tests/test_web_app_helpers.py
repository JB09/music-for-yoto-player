"""Tests for the pure helpers in web_app: word extraction and match flagging."""

import os


class TestSignificantWords:
    def test_drops_stop_words_and_short_words(self, web_app):
        assert web_app._significant_words("The Wheels on the Bus") == {"wheels", "bus"}

    def test_is_case_insensitive(self, web_app):
        assert web_app._significant_words("BAA Baa BLACK sheep") == {
            "baa", "black", "sheep"
        }

    def test_splits_on_punctuation(self, web_app):
        assert web_app._significant_words("Rock-a-bye, baby!") == {"rock", "bye", "baby"}

    def test_keeps_digits(self, web_app):
        assert "123" in web_app._significant_words("Song 123")

    def test_drops_remix_style_noise(self, web_app):
        assert web_app._significant_words("Sunshine (Remix) feat. Someone") == {
            "sunshine", "someone"
        }

    def test_empty_text_yields_empty_set(self, web_app):
        assert web_app._significant_words("") == set()


class TestFlagDownloadedResults:
    def test_flags_exact_filename_match(self, web_app, output_dir):
        open(os.path.join(output_dir, "The Beatles - Yellow Submarine.mp3"), "w").close()
        results = [{"artist": "The Beatles", "title": "Yellow Submarine"}]

        web_app._flag_downloaded_results(results)

        assert results[0]["downloaded"] is True
        assert results[0]["partial_match"] == ""

    def test_flags_partial_match_on_word_overlap(self, web_app, output_dir):
        open(os.path.join(output_dir, "Beatles - Yellow Submarine (Live).mp3"), "w").close()
        results = [{"artist": "The Beatles", "title": "Yellow Submarine"}]

        web_app._flag_downloaded_results(results)

        assert results[0]["downloaded"] is False
        assert results[0]["partial_match"] == "Beatles - Yellow Submarine (Live).mp3"

    def test_unrelated_file_is_not_flagged(self, web_app, output_dir):
        open(os.path.join(output_dir, "Pinkfong - Baby Shark.mp3"), "w").close()
        results = [{"artist": "Mozart", "title": "Requiem"}]

        web_app._flag_downloaded_results(results)

        assert results[0]["downloaded"] is False
        assert results[0]["partial_match"] == ""

    def test_non_mp3_files_are_ignored_for_partial_matching(self, web_app, output_dir):
        open(os.path.join(output_dir, "Raffi - Bananaphone Song.txt"), "w").close()
        results = [{"artist": "Raffi", "title": "Bananaphone Song"}]

        web_app._flag_downloaded_results(results)

        assert results[0]["partial_match"] == ""

    def test_missing_output_dir_flags_nothing(self, web_app, monkeypatch):
        monkeypatch.setattr(web_app, "OUTPUT_DIR", "/nonexistent-dir-for-tests")
        results = [{"artist": "A", "title": "B"}, {"artist": "C", "title": "D"}]

        web_app._flag_downloaded_results(results)

        assert all(r["downloaded"] is False for r in results)
        assert all(r["partial_match"] == "" for r in results)

    def test_slashes_in_names_map_to_the_sanitised_filename(self, web_app, output_dir):
        open(os.path.join(output_dir, "AC-DC - Rock-Roll.mp3"), "w").close()
        results = [{"artist": "AC/DC", "title": "Rock/Roll"}]

        web_app._flag_downloaded_results(results)

        assert results[0]["downloaded"] is True


class TestExtractSongsFromText:
    def test_parses_fenced_json(self, web_app):
        text = '```json\n[{"title": "T", "artist": "A"}]\n```'
        assert web_app.extract_songs_from_text(text) == [{"title": "T", "artist": "A"}]

    def test_returns_none_without_fence(self, web_app):
        assert web_app.extract_songs_from_text('[{"title": "T", "artist": "A"}]') is None

    def test_returns_none_on_malformed_json(self, web_app):
        assert web_app.extract_songs_from_text('```json\n[{"title":}]\n```') is None
