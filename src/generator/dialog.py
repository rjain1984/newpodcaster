"""Generate a two-host dialog from an article using Gemini, with model fallback."""
from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from generator.types import Article, Turn

logger = logging.getLogger(__name__)

# Try models in this order. Each Gemini model has its OWN free-tier daily quota,
# so when one model 429s, falling through to the next gives us a fresh bucket.
# Ordered roughly by free-tier RPD (highest first) then by recency.
TEXT_MODELS_FALLBACK = [
    "gemini-3.1-flash-lite",  # ~500 RPD on free tier
    "gemini-2.5-flash",        # different model = separate quota bucket
    "gemini-2.5-flash-lite",   # 20 RPD on free tier
    "gemini-2.0-flash-lite",   # legacy fallback, separate quota
]
# Backward-compat export — first model is the primary.
MODEL = TEXT_MODELS_FALLBACK[0]

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
    "Tum ek Indian current-affairs podcast ke liye script likh rahe ho — "
    "Raj Shamani 'Figuring Out' style: curious, accessible, story-driven.\n"
    "\n"
    "Do hosts hain:\n"
    "  Alex (host_a) — curious interviewer. Probing 'kyun?', "
    "'kaise possible hai?', 'iska matlab kya hai?', 'common man pe asar?'\n"
    "  Sam (host_b) — the one with context. Explains in plain language, "
    "uses everyday analogies, ties facts to broader implications.\n"
    "\n"
    "**STYLE — Raj Shamani vibe:**\n"
    "  - Curiosity drives the conversation. Alex asks short probing questions, "
    "Sam answers with slightly fuller responses.\n"
    "  - Translate jargon into rozmarra language. 'GDP' / 'policy' / "
    "'inflation' ko relatable banao with concrete examples.\n"
    "  - Always tie back to practical impact: 'iska impact kya hoga aam aadmi pe?', "
    "'business pe kya असर पड़ेगा?', 'mere salary pe matter karega?'\n"
    "  - Slightly provocative when warranted — don't just describe, take a position.\n"
    "    'Lekin uska doosra side bhi hai na...'\n"
    "  - Storytelling over lecturing. Hook → set context → reveal core fact → "
    "implications → takeaway.\n"
    "\n"
    "**LANGUAGE:**\n"
    "  Hindi (Devanagari) + English (Latin) ka natural code-mix. "
    "Educated urban Indian register, not formal news anchor, not gossipy friend.\n"
    "  AVOID heavy slang fillers: यार, भाई (used sparingly OK), "
    "basically-as-filler, literally-as-filler, 'I mean' — minimize.\n"
    "  AVOID pure शुद्ध/Sanskritised Hindi (news-anchor style).\n"
    "  AVOID pure English — natural code-mixing chahiye.\n"
    "  Proper nouns, scores, brands — original form.\n"
    "\n"
    "Examples of the right register:\n"
    "  Alex: 'तो Sam, यह पूरा matter क्या है? Simple words में समझाओ.'\n"
    "  Sam: 'देखो, सरकार ने एक नया rule introduce किया है — और इसका सीधा असर "
    "हर taxpayer पर पड़ेगा.'\n"
    "  Alex: 'लेकिन यह आम लोगों के लिए actually क्यों matter करता है?'\n"
    "  Sam: 'सबसे बड़ी बात यह है कि filing आसान हो जाएगी, "
    "और कुछ exemptions भी add हुए हैं.'\n"
    "  Alex: 'और कोई downside?'\n"
    "  Sam: 'है — पुराने benefits में से कुछ remove हो रहे हैं. "
    "Long-term में देखें तो...'\n"
    "\n"
    "Article ki facts ke saath stick करो — कुछ invent मत करो.\n"
    "Target podcast length: 3-5 minutes audio (~600-1000 words of dialog).\n"
    "Structure:\n"
    "  - Strong 1-line hook (~10 sec) — Alex sets up the curiosity.\n"
    "  - Alex probes, Sam explains the core facts (~90 sec).\n"
    "  - Implications, broader context, who-is-affected (~60-90 sec).\n"
    "  - Sharp takeaway sign-off (1 line, ideally from Sam).\n"
    "Most turns 1-3 sentences. Alex's questions short and sharp; "
    "Sam's answers slightly fuller but never lectures.\n"
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


def _is_recoverable(e: genai_errors.ClientError) -> bool:
    """Decide whether to try the next model. Recoverable: 429 (quota), 404
    (model not available to this key), or 400 (model unrecognized)."""
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    return code in (400, 404, 429)


def generate_dialog(article: Article, api_key: str, topic: str | None = None) -> list[Turn]:
    user_prompt = (
        f"Article title: {article['title']}\n\n"
        f"Article body:\n{article['body']}"
    )
    client = _client(api_key)
    system_instruction = _system_prompt_for_topic(topic)

    last_recoverable_err: genai_errors.ClientError | None = None
    response = None
    used_model: str | None = None
    for model in TEXT_MODELS_FALLBACK:
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                ),
            )
            used_model = model
            logger.info("dialog generated via model=%s", model)
            break
        except genai_errors.ClientError as e:
            if _is_recoverable(e):
                logger.warning(
                    "dialog model %s unavailable (status=%s); trying next",
                    model, getattr(e, "status_code", "?"),
                )
                last_recoverable_err = e
                continue
            raise  # permanent client error — propagate

    if response is None:
        # Every model in the fallback list returned a recoverable error
        # (typically all 429s). Re-raise the last one so the handler treats
        # this as a transient failure and the URL is not marked seen.
        assert last_recoverable_err is not None
        raise last_recoverable_err

    raw = (response.text or "").strip()
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        raise DialogError(
            f"could not parse Gemini response as JSON (model={used_model}): {e}\nraw={raw!r}"
        ) from e

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
