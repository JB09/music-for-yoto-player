"""Shared test fixtures.

Importing ``web_app`` has two side effects that need to be contained before
the module is imported: it reads ``OUTPUT_DIR`` from the environment and it
builds a real music provider (which would construct a YTMusic client). Both
are neutralised here, at conftest import time, so that every test module gets
a web_app wired to a temp directory and a fake provider.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Temp download dir for the whole session — web_app reads OUTPUT_DIR on import.
_TMP_OUTPUT_DIR = tempfile.mkdtemp(prefix="yoto-tests-")
os.environ["OUTPUT_DIR"] = _TMP_OUTPUT_DIR


class FakeProvider:
    """Stand-in for a MusicProvider; records calls instead of hitting network."""

    def __init__(self, output_dir="downloads"):
        self.output_dir = output_dir
        self.search_calls = []
        self.get_audio_calls = []
        self.search_results = []

    @property
    def name(self):
        return "Fake"

    @property
    def supports_preview(self):
        return True

    def search(self, query, num_results=5):
        self.search_calls.append((query, num_results))
        return self.search_results[:num_results]

    def get_audio(self, track_id, title, artist, force=False):
        self.get_audio_calls.append((track_id, title, artist, force))
        return os.path.join(self.output_dir, f"{artist} - {title}.mp3")

    def get_preview_url(self, track_id):
        return f"https://example.invalid/{track_id}"


# Patch the factory before web_app imports it, so the module-level
# `provider = get_provider(...)` call gets the fake, then put the real factory
# back so tests can exercise it directly.
import music_providers  # noqa: E402

_real_get_provider = music_providers.get_provider
music_providers.get_provider = lambda output_dir="downloads": FakeProvider(output_dir)

import web_app as web_app_module  # noqa: E402

music_providers.get_provider = _real_get_provider


@pytest.fixture
def output_dir():
    """The temp directory web_app writes downloads into, emptied per test."""
    os.makedirs(_TMP_OUTPUT_DIR, exist_ok=True)
    for name in os.listdir(_TMP_OUTPUT_DIR):
        path = os.path.join(_TMP_OUTPUT_DIR, name)
        if os.path.isfile(path):
            os.remove(path)
    return _TMP_OUTPUT_DIR


@pytest.fixture
def web_app():
    """The imported web_app module, with a fake provider attached."""
    return web_app_module


@pytest.fixture
def fake_provider(web_app):
    """Replace web_app's provider for the duration of a test."""
    original = web_app.provider
    fake = FakeProvider(output_dir=_TMP_OUTPUT_DIR)
    web_app.provider = fake
    yield fake
    web_app.provider = original


@pytest.fixture
def client(web_app):
    """Flask test client with a fixed secret key so sessions are stable."""
    web_app.app.config["TESTING"] = True
    web_app.app.secret_key = "test-secret-key"
    with web_app.app.test_client() as c:
        yield c
