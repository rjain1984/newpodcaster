"""Generate a two-host dialog from an article using Gemini 2.5 Flash."""
from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types as genai_types

from generator.types import Article, Turn

# higher free-tier RPD than 2.5-flash; sufficient for dialog scripting
MODEL = "gemini-2.5-flash-lite"

SYSTEM_PROMPT = (
    "You are a script writer for an in-depth news podcast.\n"
    "Two hosts named Alex (host_a) and Sam (host_b) chat about a single news article.\n"
    "Tone: conversational, curious, light. Avoid jargon. "
    "Keep it accurate to the article — never invent facts.\n"
    "\n"
    "Target podcast length: 5-7 minutes of audio (~1000-1400 words of dialog). "
    "Even short source articles get the full treatment via context and analysis.\n"
    "Structure:\n"
    "  - Open with a clear hook (~30 seconds).\n"
    "  - Cover the main facts faithfully (~2-3 minutes).\n"
    "  - Explore context, background, implications, "
    "what's at stake, and what to watch next (~2-3 minutes).\n"
    "  - End with a one-line sign-off.\n"
    "Include natural exchanges: follow-up questions, light pushback, mild disagreement, "
    "occasional jokes. Most turns are 2-5 sentences; avoid one-word interjections.\n"
    "\n"
    'Output strictly a JSON array of objects, each with `speaker` '
    '(either "host_a" or "host_b") and `text`.\n'
    "Do not include any prose outside the JSON array."
)


class DialogError(RuntimeError):
    pass


def _client(api_key: str):  # extracted for easy mocking
    return genai.Client(api_key=api_key)


def generate_dialog(article: Article, api_key: str) -> list[Turn]:
    user_prompt = (
        f"Article title: {article['title']}\n\n"
        f"Article body:\n{article['body']}"
    )
    client = _client(api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )

    raw = (response.text or "").strip()
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        raise DialogError(f"could not parse Gemini response as JSON: {e}\nraw={raw!r}") from e

    if not isinstance(parsed, list) or not parsed:
        raise DialogError(f"expected non-empty JSON array, got {type(parsed).__name__}")

    turns: list[Turn] = []
    for i, item in enumerate(parsed):
        if (
            not isinstance(item, dict)
            or item.get("speaker") not in ("host_a", "host_b")
            or not isinstance(item.get("text"), str)
            or not item["text"].strip()
        ):
            raise DialogError(f"turn {i} has wrong schema: {item!r}")
        turns.append(Turn(speaker=item["speaker"], text=item["text"].strip()))
    return turns
