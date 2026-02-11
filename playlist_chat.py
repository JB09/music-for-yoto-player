"""
LLM-powered playlist generator using the Anthropic (Claude) API.

Lets users describe what kind of playlist they want in natural language,
then returns a structured list of songs. Supports multi-turn conversation
for refining the list.
"""

import json
import os
import sys

try:
    import anthropic
except ImportError:
    anthropic = None

MAX_SONGS = 12

SYSTEM_PROMPT = f"""You are a music playlist curator. The user will describe what kind of playlist they want \
(mood, genre, occasion, artist, era, etc.) and you will suggest songs.

RULES:
- Always suggest exactly {MAX_SONGS} songs unless the user asks for fewer.
- Return songs as a JSON array in a ```json code block, with each entry having "title" and "artist" fields.
- After the JSON block, add a brief friendly summary of the playlist.
- If the user asks to swap, add, or remove songs, return the FULL updated list as JSON.
- Focus on well-known, popular songs that are easy to find on YouTube.
- If the playlist is for children (Yoto Player), prefer kid-friendly content.

Example response format:
```json
[
  {{"title": "Here Comes the Sun", "artist": "The Beatles"}},
  {{"title": "Three Little Birds", "artist": "Bob Marley"}}
]
```
A cheerful morning playlist to start the day!"""


def check_api_available() -> bool:
    """Check if the Anthropic SDK is installed and API key is set."""
    if anthropic is None:
        print("Error: 'anthropic' package not installed. Run: pip install anthropic")
        return False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("  Get an API key at: https://console.anthropic.com/")
        print("  Then: set ANTHROPIC_API_KEY=sk-ant-...")
        return False
    return True


def extract_songs_from_response(text: str) -> list[dict] | None:
    """Extract the JSON song list from a Claude response."""
    # Look for ```json ... ``` block
    start = text.find("```json")
    if start == -1:
        start = text.find("```")
    if start == -1:
        return None

    start = text.find("[", start)
    end = text.find("]", start)
    if start == -1 or end == -1:
        return None

    try:
        songs = json.loads(text[start:end + 1])
        if isinstance(songs, list) and all("title" in s and "artist" in s for s in songs):
            return songs
    except json.JSONDecodeError:
        pass
    return None


def display_playlist(songs: list[dict]):
    """Pretty-print the current playlist."""
    print(f"\n  Current playlist ({len(songs)} songs):")
    print(f"  {'─'*45}")
    for i, s in enumerate(songs, 1):
        print(f"  {i:2d}. {s['title']} — {s['artist']}")
    print()


def chat_playlist() -> list[str]:
    """
    Run an interactive chat session to generate a playlist.
    Returns a list of "Title - Artist" strings.
    """
    if not check_api_available():
        sys.exit(1)

    client = anthropic.Anthropic()
    messages = []
    current_songs = []

    print("\n" + "="*60)
    print("  Playlist Chat (powered by Claude)")
    print("="*60)
    print("  Describe the playlist you want. Examples:")
    print('    "Relaxing bedtime songs for a 3-year-old"')
    print('    "Upbeat 80s road trip anthems"')
    print('    "Disney songs my kids will love"')
    print()
    print("  Commands during chat:")
    print("    done  — accept the current playlist")
    print("    quit  — exit without a playlist")
    print()

    while True:
        user_input = input("  You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("  Cancelled.")
            return []
        if user_input.lower() == "done":
            if current_songs:
                return [f"{s['title']} - {s['artist']}" for s in current_songs]
            print("  No playlist yet. Describe what you want first!")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            assistant_text = response.content[0].text
            messages.append({"role": "assistant", "content": assistant_text})

            # Try to extract songs
            songs = extract_songs_from_response(assistant_text)
            if songs:
                current_songs = songs[:MAX_SONGS]
                display_playlist(current_songs)
                # Print any text after the JSON block as the summary
                json_end = assistant_text.rfind("```")
                if json_end != -1:
                    summary = assistant_text[json_end + 3:].strip()
                    if summary:
                        print(f"  Claude: {summary}")
                print("  Type 'done' to accept, or ask to change songs.")
            else:
                # No JSON found — just display the text response
                print(f"\n  Claude: {assistant_text}\n")

        except anthropic.APIError as e:
            print(f"\n  API error: {e}\n")
        except Exception as e:
            print(f"\n  Error: {e}\n")
