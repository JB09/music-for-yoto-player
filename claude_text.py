"""
Shared helper for the app's short, single-shot Claude requests.

Claude Sonnet 5.5 can return thinking blocks (and, after a server-side
fallback, a fallback block) before the text, so callers must not assume
response.content[0] is text. ask_claude() returns the concatenated text,
or "" if the request was declined.
"""

import anthropic

MODEL = "claude-sonnet-5-5"


def ask_claude(client: anthropic.Anthropic, *, max_tokens: int,
               messages: list[dict], system: str | None = None) -> str:
    kwargs = {"system": system} if system else {}
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        # Chat, picking and short generation: low effort keeps thinking short
        # and skips it on most simple requests.
        output_config={"effort": "low"},
        # On a refusal in a category Sonnet 5.5 declines but Sonnet 5 doesn't,
        # retry server-side instead of returning nothing.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=messages,
        **kwargs,
    )
    if response.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in response.content if b.type == "text")
