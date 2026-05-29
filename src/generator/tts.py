"""Render dialog turns to multi-speaker audio via Gemini TTS, with model fallback."""
from __future__ import annotations

import io
import logging
import wave

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from generator.types import Turn

logger = logging.getLogger(__name__)

# Each Gemini TTS model has its own free-tier quota bucket. When the primary
# 429s on quota, fall through to the next. The chain mixes Flash + Pro variants
# so the buckets are genuinely separate.
TTS_MODELS_FALLBACK = [
    "gemini-2.5-flash-preview-tts",  # current default; ~10 RPD free tier
    "gemini-2.5-pro-preview-tts",    # Pro variant, separate quota bucket
    "gemini-3.0-flash-tts",          # newer model if available on this key
]
# Backward-compat: first model is the primary
MODEL = TTS_MODELS_FALLBACK[0]

HOST_A_NAME = "Alex"
HOST_B_NAME = "Sam"
HOST_A_VOICE = "Charon"
HOST_B_VOICE = "Kore"

# Gemini multi-speaker TTS returns raw 16-bit PCM at 24 kHz mono.
PCM_SAMPLE_RATE_HZ = 24000
PCM_SAMPLE_WIDTH_BYTES = 2
PCM_CHANNELS = 1


class TtsError(RuntimeError):
    pass


def _client(api_key: str):
    return genai.Client(api_key=api_key)


def _is_recoverable(e: genai_errors.ClientError) -> bool:
    """429 (quota), 404 (model not available), or 400 (model unrecognized)."""
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code is not None:
        return code in (400, 404, 429)
    return any(c in str(e)[:50] for c in ("429", "404", "400"))


def _build_speech_config() -> genai_types.SpeechConfig:
    return genai_types.SpeechConfig(
        multi_speaker_voice_config=genai_types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                genai_types.SpeakerVoiceConfig(
                    speaker=HOST_A_NAME,
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=HOST_A_VOICE,
                        ),
                    ),
                ),
                genai_types.SpeakerVoiceConfig(
                    speaker=HOST_B_NAME,
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=HOST_B_VOICE,
                        ),
                    ),
                ),
            ]
        )
    )


def render_audio(turns: list[Turn], api_key: str) -> bytes:
    contents = _format_dialog(turns)
    client = _client(api_key)
    speech_config = _build_speech_config()

    last_recoverable_err: genai_errors.ClientError | None = None
    response = None
    used_model: str | None = None
    for model in TTS_MODELS_FALLBACK:
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=speech_config,
                ),
            )
            used_model = model
            logger.info("tts rendered via model=%s", model)
            break
        except genai_errors.ClientError as e:
            if _is_recoverable(e):
                logger.warning(
                    "tts model %s unavailable (status=%s); trying next",
                    model,
                    getattr(e, "code", None) or getattr(e, "status_code", "?"),
                )
                last_recoverable_err = e
                continue
            raise

    if response is None:
        assert last_recoverable_err is not None
        # Re-raise so the handler treats this as transient and doesn't mark seen.
        raise last_recoverable_err

    if not response.candidates:
        raise TtsError(f"Gemini ({used_model}) returned no candidates")
    parts = response.candidates[0].content.parts
    if not parts or not getattr(parts[0], "inline_data", None):
        raise TtsError(f"Gemini ({used_model}) response has no audio data")
    return _wrap_pcm_in_wav(parts[0].inline_data.data)


def _wrap_pcm_in_wav(pcm: bytes) -> bytes:
    """Wrap raw PCM bytes in a WAV container so browser audio players can
    determine duration and seek properly. Gemini's TTS returns headerless PCM."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(PCM_CHANNELS)
        wav.setsampwidth(PCM_SAMPLE_WIDTH_BYTES)
        wav.setframerate(PCM_SAMPLE_RATE_HZ)
        wav.writeframes(pcm)
    return buf.getvalue()


def _format_dialog(turns: list[Turn]) -> str:
    lines = []
    for t in turns:
        name = HOST_A_NAME if t["speaker"] == "host_a" else HOST_B_NAME
        lines.append(f"{name}: {t['text']}")
    return "\n".join(lines)
