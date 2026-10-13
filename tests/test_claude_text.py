"""Tests for the shared Claude request helper."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

import claude_text


@pytest.fixture(autouse=True)
def fresh_model_cache(monkeypatch):
    monkeypatch.setattr(claude_text, "_newest", None)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)


def _block(type_, text=""):
    return SimpleNamespace(type=type_, text=text)


def _model(id_, created_at):
    return SimpleNamespace(id=id_, created_at=created_at)


MODELS = [
    _model("claude-opus-5-5", "2026-09-01"),
    _model("claude-sonnet-5-5", "2026-08-01"),
    _model("claude-sonnet-5", "2026-03-01"),
    _model("claude-haiku-5-5", "2026-09-15"),
]


class FakeClient:
    def __init__(self, response, models=MODELS, reject=()):
        self.response = response
        self.calls = []
        self.list_calls = 0
        self._models = models
        self._reject = reject
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=self._list)

    def _list(self):
        self.list_calls += 1
        if isinstance(self._models, Exception):
            raise self._models
        return iter(self._models)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["model"] in self._reject:
            req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.BadRequestError(
                "bad", response=httpx2.Response(400, request=req), body=None)
        return self.response


def _ok():
    return SimpleNamespace(stop_reason="end_turn", content=[_block("text", "ok")])


def test_returns_text_after_thinking_blocks():
    client = FakeClient(SimpleNamespace(
        stop_reason="end_turn",
        content=[_block("thinking"), _block("text", "Hello "), _block("text", "there")],
    ))
    assert claude_text.ask_claude(client, max_tokens=100, messages=[]) == "Hello there"


def test_refusal_returns_empty_string():
    client = FakeClient(SimpleNamespace(stop_reason="refusal", content=[]))
    assert claude_text.ask_claude(client, max_tokens=100, messages=[]) == ""


def test_request_shape():
    client = FakeClient(SimpleNamespace(stop_reason="end_turn", content=[]))
    claude_text.ask_claude(client, max_tokens=123, system="sys",
                           messages=[{"role": "user", "content": "hi"}])
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["max_tokens"] == 123
    assert call["system"] == "sys"
    assert call["output_config"] == {"effort": "low"}
    assert call["fallbacks"] == "default"


def test_system_omitted_when_not_given():
    client = FakeClient(SimpleNamespace(stop_reason="end_turn", content=[]))
    claude_text.ask_claude(client, max_tokens=1, messages=[])
    assert "system" not in client.calls[0]


def test_picks_newest_sonnet_and_caches_lookup():
    newer = MODELS + [_model("claude-sonnet-6", "2026-12-01")]
    client = FakeClient(_ok(), models=newer)
    claude_text.ask_claude(client, max_tokens=1, messages=[])
    # A new client per request (as the app does) still reuses the lookup.
    client2 = FakeClient(_ok(), models=newer)
    claude_text.ask_claude(client2, max_tokens=1, messages=[])
    assert client.calls[0]["model"] == "claude-sonnet-6"
    assert client2.calls[0]["model"] == "claude-sonnet-6"
    assert client.list_calls + client2.list_calls == 1


def test_env_override_skips_lookup(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5-5")
    client = FakeClient(_ok())
    claude_text.ask_claude(client, max_tokens=1, messages=[])
    assert client.calls[0]["model"] == "claude-opus-5-5"
    assert client.list_calls == 0


def test_lookup_failure_uses_fallback_model():
    req = httpx2.Request("GET", "https://api.anthropic.com/v1/models")
    client = FakeClient(_ok(), models=anthropic.APIConnectionError(request=req))
    claude_text.ask_claude(client, max_tokens=1, messages=[])
    assert client.calls[0]["model"] == claude_text.FALLBACK_MODEL
    # The failure isn't cached: a later request looks up again.
    client2 = FakeClient(_ok())
    claude_text.ask_claude(client2, max_tokens=1, messages=[])
    assert client2.list_calls == 1


def test_rejected_request_retries_on_fallback_model():
    newer = MODELS + [_model("claude-sonnet-6", "2026-12-01")]
    client = FakeClient(_ok(), models=newer, reject=("claude-sonnet-6",))
    assert claude_text.ask_claude(client, max_tokens=1, messages=[]) == "ok"
    assert [c["model"] for c in client.calls] == ["claude-sonnet-6", claude_text.FALLBACK_MODEL]
