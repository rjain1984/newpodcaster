"""Generate a two-host dialog from an article using Gemini 2.5 Flash."""
from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types as genai_types

from generator.types import Article, Turn

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "You are a script writer for a short news podcast.\n"
    "Two hosts named Alex (host_a) and Sam (host_b) chat about a single news article.\n"
    "Tone: conversational, curious, light. Avoid jargon. "
    "Keep it accurate to the article — never invent facts.\n"
    'Output strictly a JSON array of objects, each with `speaker` '
    '(either "host_a" or "host_b") and `text`.\n'
    "Aim for ~1 minute of audio per 300 words of source. Most turns are 1-3 sentences.\n"
    "Start with a short hook, then conversational back-and-forth, end with a one-line sign-off.\n"
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
