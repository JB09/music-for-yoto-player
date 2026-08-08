"""End-to-end tests of the Flask wizard routes via the test client."""

import os


def set_session(client, **values):
    with client.session_transaction() as sess:
        sess.update(values)


def make_results(count=3):
    return [
        {
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "success": True,
            "filepath": f"/downloads/Artist {i} - Song {i}.mp3",
        }
        for i in range(count)
    ]


class TestIndex:
    def test_renders(self, client):
        assert client.get("/").status_code == 200

    def test_clears_previous_session_state(self, client):
        set_session(client, raw_songs=["old"], shuffled=True)

        client.get("/")

        with client.session_transaction() as sess:
            assert "raw_songs" not in sess


class TestTextInput:
    def test_get_renders_the_form(self, client):
        assert client.get("/text").status_code == 200

    def test_post_stores_songs_and_redirects_to_review(self, client):
        resp = client.post("/text", data={"songs": "Song A\nSong B"})

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/review")
        with client.session_transaction() as sess:
            assert sess["raw_songs"] == ["Song A", "Song B"]
            assert sess["input_mode"] == "text"

    def test_blank_lines_and_comments_are_skipped(self, client):
        client.post("/text", data={"songs": "  Song A  \n\n# a comment\nSong B\n"})

        with client.session_transaction() as sess:
            assert sess["raw_songs"] == ["Song A", "Song B"]

    def test_empty_submission_re_renders_the_form(self, client):
        resp = client.post("/text", data={"songs": "   \n\n"})

        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert "raw_songs" not in sess


class TestReview:
    def test_redirects_home_when_there_is_nothing_to_review(self, client):
        resp = client.get("/review")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/")

    def test_text_mode_caps_at_the_card_limit(self, client, web_app):
        songs = [f"Song {i}" for i in range(150)]
        set_session(client, raw_songs=songs, input_mode="text")

        assert client.get("/review").status_code == 200
        with client.session_transaction() as sess:
            assert len(sess["raw_songs"]) == web_app.MAX_TRACKS_PER_CARD

    def test_chat_mode_caps_at_max_songs(self, client, web_app):
        songs = [f"Song {i}" for i in range(50)]
        set_session(client, raw_songs=songs, input_mode="chat")

        client.get("/review")

        with client.session_transaction() as sess:
            assert len(sess["raw_songs"]) == web_app.MAX_SONGS

    def test_shuffle_happens_only_once(self, client):
        set_session(client, raw_songs=[f"Song {i}" for i in range(10)],
                    input_mode="text")

        client.get("/review")
        with client.session_transaction() as sess:
            first = list(sess["raw_songs"])

        client.get("/review")
        with client.session_transaction() as sess:
            assert sess["raw_songs"] == first

    def test_post_starts_matching(self, client):
        set_session(client, raw_songs=["Song A"], input_mode="text")

        resp = client.post("/review")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/match")
        with client.session_transaction() as sess:
            assert sess["match_index"] == 0
            assert sess["confirmed_songs"] == []

    def test_reshuffle_clears_the_shuffled_flag(self, client):
        set_session(client, raw_songs=["A", "B"], input_mode="text", shuffled=True)

        resp = client.post("/review/reshuffle")

        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert "shuffled" not in sess


class TestReviewReorder:
    def test_stores_the_new_order(self, client):
        set_session(client, raw_songs=["A", "B", "C"], input_mode="text")

        resp = client.post("/review/reorder", json={"songs": ["C", "A", "B"]})

        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}
        with client.session_transaction() as sess:
            assert sess["raw_songs"] == ["C", "A", "B"]

    def test_caps_the_submitted_list(self, client, web_app):
        set_session(client, input_mode="chat")

        client.post("/review/reorder", json={"songs": [f"S{i}" for i in range(40)]})

        with client.session_transaction() as sess:
            assert len(sess["raw_songs"]) == web_app.MAX_SONGS

    def test_ignores_a_payload_without_songs(self, client):
        set_session(client, raw_songs=["A"], input_mode="text")

        assert client.post("/review/reorder", json={}).status_code == 200
        with client.session_transaction() as sess:
            assert sess["raw_songs"] == ["A"]


class TestTrackReorder:
    def test_reorders_results(self, client):
        set_session(client, download_results=make_results(3))

        resp = client.post("/track/reorder", json={"order": [2, 0, 1]})

        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert [r["title"] for r in sess["download_results"]] == [
                "Song 2", "Song 0", "Song 1"
            ]

    def test_rejects_an_incomplete_order(self, client):
        set_session(client, download_results=make_results(3))

        resp = client.post("/track/reorder", json={"order": [0, 1]})

        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_rejects_out_of_range_indices(self, client):
        set_session(client, download_results=make_results(2))

        assert client.post("/track/reorder", json={"order": [0, 5]}).status_code == 400

    def test_rejects_a_missing_payload(self, client):
        assert client.post("/track/reorder", json={}).status_code == 400


class TestTrackDelete:
    def test_removes_the_track_and_returns_the_count(self, client):
        set_session(client, download_results=make_results(3))

        resp = client.post("/track/delete", json={"index": 1})

        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True, "count": 2}
        with client.session_transaction() as sess:
            assert [r["title"] for r in sess["download_results"]] == [
                "Song 0", "Song 2"
            ]

    def test_rejects_an_out_of_range_index(self, client):
        set_session(client, download_results=make_results(2))

        assert client.post("/track/delete", json={"index": 7}).status_code == 400

    def test_rejects_a_negative_index(self, client):
        set_session(client, download_results=make_results(2))

        assert client.post("/track/delete", json={"index": -1}).status_code == 400

    def test_rejects_a_missing_index(self, client):
        set_session(client, download_results=make_results(2))

        assert client.post("/track/delete", json={}).status_code == 400


class TestTrackRename:
    def test_renames_the_file_and_updates_the_session(self, client, output_dir):
        old_path = os.path.join(output_dir, "Old Artist - Old Title.mp3")
        with open(old_path, "wb") as f:
            f.write(b"audio")
        set_session(client, download_results=[
            {"title": "Old Title", "artist": "Old Artist",
             "success": True, "filepath": old_path}
        ])

        resp = client.post("/track/rename", json={
            "index": 0, "title": "New Title", "artist": "New Artist",
        })

        new_path = os.path.join(output_dir, "New Artist - New Title.mp3")
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True, "filepath": new_path}
        assert os.path.exists(new_path) and not os.path.exists(old_path)
        with client.session_transaction() as sess:
            assert sess["download_results"][0]["title"] == "New Title"
            assert sess["download_results"][0]["filepath"] == new_path

    def test_sanitises_slashes_in_the_new_name(self, client, output_dir):
        old_path = os.path.join(output_dir, "A - B.mp3")
        with open(old_path, "wb") as f:
            f.write(b"audio")
        set_session(client, download_results=[
            {"title": "B", "artist": "A", "success": True, "filepath": old_path}
        ])

        resp = client.post("/track/rename", json={
            "index": 0, "title": "Rock/Roll", "artist": "AC\\DC",
        })

        expected = os.path.join(output_dir, "AC-DC - Rock-Roll.mp3")
        assert resp.get_json()["filepath"] == expected
        assert os.path.exists(expected)

    def test_requires_both_title_and_artist(self, client, output_dir):
        path = os.path.join(output_dir, "A - B.mp3")
        with open(path, "wb") as f:
            f.write(b"audio")
        set_session(client, download_results=[
            {"title": "B", "artist": "A", "success": True, "filepath": path}
        ])

        resp = client.post("/track/rename", json={
            "index": 0, "title": "  ", "artist": "New",
        })

        assert resp.status_code == 400
        assert os.path.exists(path)

    def test_rejects_a_track_with_no_file(self, client):
        set_session(client, download_results=[
            {"title": "B", "artist": "A", "success": False, "filepath": ""}
        ])

        resp = client.post("/track/rename", json={
            "index": 0, "title": "T", "artist": "A",
        })

        assert resp.status_code == 400

    def test_rejects_an_invalid_index(self, client):
        set_session(client, download_results=make_results(1))

        resp = client.post("/track/rename", json={
            "index": 9, "title": "T", "artist": "A",
        })

        assert resp.status_code == 400

    def test_rejects_an_empty_payload(self, client):
        assert client.post("/track/rename", json={}).status_code == 400
