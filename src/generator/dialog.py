"""Generate a two-host dialog from an article using Gemini 2.5 Flash."""
from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types as genai_types

from generator.types import Article, Turn

# Gemini 3.1 Flash Lite — much higher free-tier RPD (~500) than 2.5-flash-lite (~20),
# sufficient for dialog scripting across 4 topics × 5 articles/day with headroom.
MODEL = "gemini-3.1-flash-lite"

SYSTEM_PROMPT_EN = (
    "You are a script writer for a snappy news podcast.\n"
    "Two hosts named Alex (host_a) and Sam (host_b) chat about a single news article.\n"
    "Tone: conversational, punchy, energetic. Avoid jargon. "
    "Keep it accurate to the article — never invent facts.\n"
    "\n"
    "Target podcast length: 3-5 minutes of audio (~600-1000 words of dialog). "
    "Be concise. Trim filler. Prefer short, declarative sentences.\n"
    "Structure:\n"
    "  - Open with a 1-line hook (~10 seconds).\n"
    "  - Cover the main facts faithfully (~90 seconds).\n"
    "  - Quick context, implications, what to watch next (~60-90 seconds).\n"
    "  - End with a one-line sign-off.\n"
    "Most turns are 1-3 sentences. No long monologues. No filler.\n"
    "\n"
    'Output strictly a JSON array of objects, each with `speaker` '
    '(either "host_a" or "host_b") and `text`.\n'
    "Do not include any prose outside the JSON array."
)

SYSTEM_PROMPT_HINGLISH = (
    "Tum ek snappy news podcast ke liye script likh rahe ho.\n"
    "Do hosts hain — Alex (host_a) aur Sam (host_b) — ek news article par baat kar rahe hain.\n"
    "\n"
    "**LANGUAGE — VERY IMPORTANT:**\n"
    "Dialog NATURAL CONVERSATIONAL HINGLISH mein likho — Hindi aur English ka casual mix, "
    "jaise urban Indians normally bolte hain. "
    "Devanagari script for Hindi words and Latin for English.\n"
    "AVOID karo pure literary/शुद्ध Hindi (Sanskritised, news-anchor style). "
    "AVOID karo pure English bhi. Real, friendly Hinglish chahiye.\n"
    "Examples of the vibe we want:\n"
    "  'Toh यार, ये news pretty interesting hai.'\n"
    "  'Bilkul, और जो main point है vo ये hai...'\n"
    "  'I mean, क्या ये actually game-changer है?'\n"
    "  'Achha तो basically...'\n"
    "Common conversational glue: यार, भाई, अच्छा, सही है, मतलब, basically, actually, "
    "literally, बस, तो, फिर, देखो, सुनो.\n"
    "Proper nouns and technical terms (team names, places, brands) stay in their original form. "
    "Numbers, scores, and English idioms used naturally are fine.\n"
    "Tone: conversational, punchy, friendly — like two friends discussing news over chai.\n"
    "\n"
    "Article ki facts ke saath stick karo — kuch invent मत करो.\n"
    "Target podcast length: 3-5 minutes audio (~600-1000 words of dialog).\n"
    "Structure:\n"
    "  - 1-line hook se start karo (~10 sec).\n"
    "  - Main facts (~90 sec).\n"
    "  - Quick context, implications, kya watch karna hai (~60-90 sec).\n"
    "  - Ek line ka sign-off.\n"
    "Most turns 1-3 sentences ke. No long monologues, no filler.\n"
    "\n"
    'Output strictly a JSON array — each item: `speaker` ("host_a" or "host_b") and `text`. '
    "No prose outside the JSON array."
)


def _system_prompt_for_topic(topic: str | None) -> str:
    return SYSTEM_PROMPT_HINGLISH if topic == "hindi" else SYSTEM_PROMPT_EN


class DialogError(RuntimeError):
    pass


def _client(api_key: str):  # extracted for easy mocking
    return genai.Client(api_key=api_key)


def generate_dialog(article: Article, api_key: str, topic: str | None = None) -> list[Turn]:
    user_prompt = (
        f"Article title: {article['title']}\n\n"
        f"Article body:\n{article['body']}"
    )
    client = _client(api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=_system_prompt_for_topic(topic),
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
