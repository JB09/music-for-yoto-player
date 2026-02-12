"""
AI-powered icon and cover image selection for Yoto MYO cards.

Icons:
  1. Pick the best-matching public icon from the Yoto shared library.
  2. Generate a custom 16x16 pixel icon via AI (requires ANTHROPIC_API_KEY).

Cover images:
  3. Generate a custom cover image via AI (requires ANTHROPIC_API_KEY + Pillow).

The Yoto Player display supports 16x16 pixel icons in PNG format.
Cover images are larger artwork shown in the Yoto app.
"""

import base64
import io
import json
import os

try:
    import anthropic
except ImportError:
    anthropic = None


def select_public_icon(public_icons: list[dict], song_titles: list[str],
                       card_name: str) -> dict | None:
    """
    Use Claude to pick the best public icon for the playlist.

    Args:
        public_icons: List of icon dicts from Yoto API (with _id, url, etc.)
        song_titles: List of song title strings in the playlist.
        card_name: The name of the MYO card/playlist.

    Returns:
        The chosen icon dict, or None if selection fails.
    """
    if not public_icons or anthropic is None:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    # Build a concise list of icons for Claude to choose from
    icon_list = []
    for icon in public_icons:
        icon_id = icon.get("mediaId") or icon.get("_id", "")
        url = icon.get("url", "")
        # Some icons have descriptive filenames or tags
        name = icon.get("name", icon.get("filename", ""))
        icon_list.append({"id": icon_id, "url": url, "name": name})

    prompt = (
        f"You are selecting a 16x16 pixel display icon for a Yoto Player MYO card.\n\n"
        f"Card name: \"{card_name}\"\n"
        f"Songs on this card:\n"
    )
    for i, title in enumerate(song_titles, 1):
        prompt += f"  {i}. {title}\n"

    prompt += (
        f"\nHere are the available public icons (id and name):\n"
        f"```json\n{json.dumps(icon_list, indent=2)}\n```\n\n"
        f"Pick the ONE icon that best represents this playlist's theme or mood. "
        f"If the playlist is for kids/bedtime, pick something child-friendly. "
        f"If it's music-themed, pick a music icon. Etc.\n\n"
        f"Respond with ONLY a JSON object: {{\"icon_id\": \"<the chosen id>\", \"reason\": \"<brief reason>\"}}"
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            chosen_id = result.get("icon_id", "")
            reason = result.get("reason", "")

            # Find the matching icon
            for icon in public_icons:
                icon_id = icon.get("mediaId") or icon.get("_id", "")
                if icon_id == chosen_id:
                    return {**icon, "_selection_reason": reason}

    except Exception:
        pass

    return None


def generate_custom_icon(song_titles: list[str], card_name: str) -> bytes | None:
    """
    Use Claude to generate Python code that creates a 16x16 pixel icon,
    then execute it to produce the PNG bytes.

    Args:
        song_titles: List of song title strings.
        card_name: The name of the MYO card/playlist.

    Returns:
        PNG image bytes (16x16), or None on failure.
    """
    if anthropic is None:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = (
        f"Generate Python code that creates a 16x16 pixel PNG icon for a Yoto Player MYO card.\n\n"
        f"Card name: \"{card_name}\"\n"
        f"Songs:\n"
    )
    for i, title in enumerate(song_titles, 1):
        prompt += f"  {i}. {title}\n"

    prompt += (
        f"\nRequirements:\n"
        f"- Use only the Python standard library (no PIL/Pillow) — use the `struct` and `zlib` "
        f"modules to write a raw PNG file.\n"
        f"- Output must be exactly 16x16 pixels, RGBA, 24-bit with alpha.\n"
        f"- Design a simple, recognizable pixel art icon that represents the playlist theme.\n"
        f"- Use bright, saturated colors (the Yoto display is small).\n"
        f"- Keep it simple — this is 16x16 pixel art.\n"
        f"- The code should define a function `create_icon() -> bytes` that returns the PNG bytes.\n"
        f"- Only output the Python code in a ```python code block, nothing else.\n"
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # Extract Python code
        start = text.find("```python")
        if start == -1:
            start = text.find("```")
        if start == -1:
            return None

        code_start = text.find("\n", start) + 1
        code_end = text.find("```", code_start)
        if code_end == -1:
            return None

        code = text[code_start:code_end].strip()

        # Execute the generated code in a restricted namespace
        namespace = {}
        exec(code, namespace)  # noqa: S102

        create_fn = namespace.get("create_icon")
        if create_fn and callable(create_fn):
            result = create_fn()
            if isinstance(result, bytes) and len(result) > 0:
                return result

    except Exception:
        pass

    return None


def generate_cover_image(song_titles: list[str], card_name: str,
                         keywords: str = "") -> bytes | None:
    """
    Use Claude to generate Python code that creates a cover image using Pillow,
    then execute it to produce JPEG bytes.

    Args:
        song_titles: List of song title strings.
        card_name: The name of the MYO card/playlist.
        keywords: Optional keywords to guide the style/theme.

    Returns:
        JPEG image bytes, or None on failure.
    """
    if anthropic is None:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = (
        f"Generate Python code that creates a cover image for a children's audio playlist card.\n\n"
        f"Card name: \"{card_name}\"\n"
        f"Songs:\n"
    )
    for i, title in enumerate(song_titles[:10], 1):
        prompt += f"  {i}. {title}\n"

    if keywords:
        prompt += f"\nStyle/theme keywords: {keywords}\n"

    prompt += (
        f"\nRequirements:\n"
        f"- Use PIL/Pillow (from PIL import Image, ImageDraw, ImageFont).\n"
        f"- Output must be 500x500 pixels, RGB, saved as JPEG.\n"
        f"- Create an appealing, colorful, child-friendly design.\n"
        f"- Use bold geometric shapes, gradients, and patterns — no text rendering "
        f"(Pillow default font is too small and ugly at this scale).\n"
        f"- Think: abstract art, simple illustrations, color blocks, patterns.\n"
        f"- Use a cohesive color palette that fits the playlist mood.\n"
        f"- The code should define a function `create_cover() -> bytes` that returns JPEG bytes.\n"
        f"- Use io.BytesIO to return the bytes (import io).\n"
        f"- Only output the Python code in a ```python code block, nothing else.\n"
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # Extract Python code
        start = text.find("```python")
        if start == -1:
            start = text.find("```")
        if start == -1:
            return None

        code_start = text.find("\n", start) + 1
        code_end = text.find("```", code_start)
        if code_end == -1:
            return None

        code = text[code_start:code_end].strip()

        # Execute the generated code
        namespace = {}
        exec(code, namespace)  # noqa: S102

        create_fn = namespace.get("create_cover")
        if create_fn and callable(create_fn):
            result = create_fn()
            if isinstance(result, bytes) and len(result) > 0:
                return result

    except Exception:
        pass

    return None


def select_icon_for_card(yoto_client, song_titles: list[str], card_name: str,
                         prefer_generate: bool = False) -> str | None:
    """
    High-level function: pick or generate an icon and upload it to Yoto.

    Tries public icon selection first (fast, no generation needed).
    Falls back to AI-generated icon if no good public match or if prefer_generate=True.

    Args:
        yoto_client: Authenticated YotoClient instance.
        song_titles: List of "Title - Artist" strings.
        card_name: Name of the MYO card.
        prefer_generate: If True, try generating a custom icon first.

    Returns:
        The icon mediaId string to use in create_myo_card(), or None.
    """
    icon_media_id = None

    if not prefer_generate:
        # Strategy 1: Pick from public icons
        try:
            print("    Selecting card icon from Yoto public library...", flush=True)
            public_icons = yoto_client.get_public_icons()
            if public_icons:
                chosen = select_public_icon(public_icons, song_titles, card_name)
                if chosen:
                    icon_media_id = chosen.get("mediaId") or chosen.get("_id")
                    reason = chosen.get("_selection_reason", "")
                    print(f"    Selected icon: {chosen.get('name', icon_media_id)}"
                          f"{f' ({reason})' if reason else ''}", flush=True)
                    return icon_media_id
        except Exception as e:
            print(f"    Could not fetch public icons: {e}", flush=True)

    # Strategy 2: Generate a custom icon
    try:
        print("    Generating custom card icon with AI...", flush=True)
        icon_bytes = generate_custom_icon(song_titles, card_name)
        if icon_bytes:
            result = yoto_client.upload_custom_icon(icon_bytes, filename="playlist-icon.png")
            icon_media_id = result.get("mediaId") or result.get("_id")
            print(f"    Custom icon uploaded: {icon_media_id}", flush=True)
            return icon_media_id
        else:
            print("    Icon generation failed, continuing without icon.", flush=True)
    except Exception as e:
        print(f"    Icon upload failed: {e}", flush=True)

    return icon_media_id
