"""Render a list of dialog turns to multi-speaker audio via Gemini TTS."""
from __future__ import annotations

from google import genai
from google.genai import types as genai_types

from generator.types import Turn

MODEL = "gemini-2.5-flash-preview-tts"
HOST_A_NAME = "Alex"
HOST_B_NAME = "Sam"
HOST_A_VOICE = "Charon"
HOST_B_VOICE = "Kore"


class TtsError(RuntimeError):
    pass


def _client(api_key: str):
    return genai.Client(api_key=api_key)


def render_audio(turns: list[Turn], api_key: str) -> bytes:
    contents = _format_dialog(turns)
    client = _client(api_key)

    speech_config = genai_types.SpeechConfig(
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

    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
        ),
    )

    if not response.candidates:
        raise TtsError("Gemini returned no candidates")
    parts = response.candidates[0].content.parts
    if not parts or not getattr(parts[0], "inline_data", None):
        raise TtsError("Gemini response has no audio data")
    return parts[0].inline_data.data


def _format_dialog(turns: list[Turn]) -> str:
    lines = []
    for t in turns:
        name = HOST_A_NAME if t["speaker"] == "host_a" else HOST_B_NAME
        lines.append(f"{name}: {t['text']}")
    return "\n".join(lines)
