"""Tests for the shared Claude request helper."""

from types import SimpleNamespace

import claude_text


def _block(type_, text=""):
    return SimpleNamespace(type=type_, text=text)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


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
    assert call["model"] == claude_text.MODEL
    assert call["max_tokens"] == 123
    assert call["system"] == "sys"
    assert call["output_config"] == {"effort": "low"}
    assert call["fallbacks"] == "default"


def test_system_omitted_when_not_given():
    client = FakeClient(SimpleNamespace(stop_reason="end_turn", content=[]))
    claude_text.ask_claude(client, max_tokens=1, messages=[])
    assert "system" not in client.calls[0]
