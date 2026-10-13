"""
Shared helper for the app's short, single-shot Claude requests.

The model is the newest Claude Sonnet, looked up once per process from the
Models API, so the app moves to new Sonnet releases without a code change.
Set CLAUDE_MODEL to pin a specific model instead.

Recent Sonnet models can return thinking blocks (and, after a server-side
fallback, a fallback block) before the text, so callers must not assume
response.content[0] is text. ask_claude() returns the concatenated text,
or "" if the request was declined.
"""

import logging
import os

import anthropic

# Used when the Models API can't be reached, and as the retry target if the
# newest Sonnet rejects this request shape.
FALLBACK_MODEL = "claude-sonnet-5-5"

log = logging.getLogger(__name__)

_newest: str | None = None


def _newest_sonnet(client: anthropic.Anthropic) -> str:
    """Return the newest Sonnet ID, looking it up once per process.

    A failed lookup isn't cached, so the next request tries again.
    """
    global _newest
    if _newest is None:
        try:
            sonnets = [m for m in client.models.list() if m.id.startswith("claude-sonnet-")]
        except anthropic.APIError as e:
            log.warning("Model lookup failed (%s); using %s", e, FALLBACK_MODEL)
            return FALLBACK_MODEL
        if not sonnets:
            return FALLBACK_MODEL
        _newest = max(sonnets, key=lambda m: m.created_at).id
        log.info("Using %s", _newest)
    return _newest


def current_model(client: anthropic.Anthropic) -> str:
    return os.environ.get("CLAUDE_MODEL") or _newest_sonnet(client)


def _create(client: anthropic.Anthropic, model: str, kwargs: dict):
    return client.beta.messages.create(
        model=model,
        # Chat, picking and short generation: low effort keeps thinking short
        # and skips it on most simple requests.
        output_config={"effort": "low"},
        # On a refusal, retry server-side on another model instead of
        # returning nothing.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        **kwargs,
    )


def ask_claude(client: anthropic.Anthropic, *, max_tokens: int,
               messages: list[dict], system: str | None = None) -> str:
    kwargs = {"max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system

    model = current_model(client)
    try:
        response = _create(client, model, kwargs)
    except anthropic.BadRequestError:
        # A newer Sonnet may not accept a parameter this code sends; retry
        # on the known-good model rather than failing the request.
        if model == FALLBACK_MODEL:
            raise
        log.warning("%s rejected the request; retrying on %s", model, FALLBACK_MODEL)
        response = _create(client, FALLBACK_MODEL, kwargs)

    if response.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in response.content if b.type == "text")
