from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from generator.tts import (
    HOST_A_NAME,
    HOST_B_NAME,
    TTS_MODELS_FALLBACK,
    TtsError,
    render_audio,
)


def _audio_response(audio_bytes: bytes) -> MagicMock:
    fake_part = MagicMock()
    fake_part.inline_data.data = audio_bytes
    fake_part.inline_data.mime_type = "audio/wav"
    fake_content = MagicMock()
    fake_content.parts = [fake_part]
    fake_candidate = MagicMock()
    fake_candidate.content = fake_content
    fake_response = MagicMock()
    fake_response.candidates = [fake_candidate]
    return fake_response


def test_render_audio_returns_wav_wrapped_bytes():
    """render_audio wraps the raw PCM from Gemini in a WAV container so browser
    audio players can determine duration."""
    turns = [
        {"speaker": "host_a", "text": "Welcome."},
        {"speaker": "host_b", "text": "Glad to be here."},
    ]
    fake_client = MagicMock()
    fake_pcm = b"\x00\x01" * 100  # 100 16-bit samples
    fake_client.models.generate_content.return_value = _audio_response(fake_pcm)
    with patch("generator.tts._client", return_value=fake_client):
        audio = render_audio(turns, api_key="FAKE")
    # WAV header: 'RIFF....WAVE'
    assert audio[:4] == b"RIFF"
    assert audio[8:12] == b"WAVE"
    # Wrapped output is larger than the raw PCM (header overhead)
    assert len(audio) > len(fake_pcm)
    # PCM data is preserved inside the container (find it after the header)
    assert fake_pcm in audio


def test_render_audio_passes_speaker_config():
    turns = [{"speaker": "host_a", "text": "hi"}]
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _audio_response(b"x")
    with patch("generator.tts._client", return_value=fake_client):
        render_audio(turns, api_key="FAKE")
    call = fake_client.models.generate_content.call_args
    config = call.kwargs["config"]
    speakers = config.speech_config.multi_speaker_voice_config.speaker_voice_configs
    names = [s.speaker for s in speakers]
    assert names == [HOST_A_NAME, HOST_B_NAME]


def test_render_audio_raises_when_no_audio():
    turns = [{"speaker": "host_a", "text": "hi"}]
    fake_client = MagicMock()
    empty = MagicMock()
    empty.candidates = []
    fake_client.models.generate_content.return_value = empty
    with patch("generator.tts._client", return_value=fake_client):
        with pytest.raises(TtsError):
            render_audio(turns, api_key="FAKE")


def test_render_audio_formats_input_with_speaker_names():
    turns = [
        {"speaker": "host_a", "text": "Hello."},
        {"speaker": "host_b", "text": "Hi back."},
    ]
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _audio_response(b"x")
    with patch("generator.tts._client", return_value=fake_client):
        render_audio(turns, api_key="FAKE")
    call = fake_client.models.generate_content.call_args
    contents = call.kwargs["contents"]
    assert f"{HOST_A_NAME}: Hello." in contents
    assert f"{HOST_B_NAME}: Hi back." in contents


def _quota_err(model: str) -> genai_errors.ClientError:
    return genai_errors.ClientError(
        429,
        {"error": {"code": 429, "message": f"quota exceeded for {model}"}},
        None,
    )


def _model_not_found_err(model: str) -> genai_errors.ClientError:
    return genai_errors.ClientError(
        404,
        {"error": {"code": 404, "message": f"model {model} not found"}},
        None,
    )


def test_render_audio_falls_through_to_next_model_on_quota():
    """When the primary TTS model 429s, try the next one in TTS_MODELS_FALLBACK."""
    turns = [{"speaker": "host_a", "text": "hi"}]
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        _quota_err(TTS_MODELS_FALLBACK[0]),
        _audio_response(b"\x00\x01" * 50),
    ]
    with patch("generator.tts._client", return_value=fake_client):
        audio = render_audio(turns, api_key="FAKE")
    assert audio[:4] == b"RIFF"
    assert fake_client.models.generate_content.call_count == 2
    second_call = fake_client.models.generate_content.call_args_list[1]
    assert second_call.kwargs["model"] == TTS_MODELS_FALLBACK[1]


def test_render_audio_falls_through_on_model_not_found():
    """A 404 from one model (e.g. preview model unavailable to the key) skips to the next."""
    turns = [{"speaker": "host_a", "text": "hi"}]
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        _model_not_found_err(TTS_MODELS_FALLBACK[0]),
        _audio_response(b"\x00\x01" * 50),
    ]
    with patch("generator.tts._client", return_value=fake_client):
        audio = render_audio(turns, api_key="FAKE")
    assert audio[:4] == b"RIFF"


def test_render_audio_reraises_when_all_models_exhausted():
    """If every TTS model 429s, propagate the last error so the handler
    treats it as transient and the URL isn't marked seen."""
    turns = [{"speaker": "host_a", "text": "hi"}]
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        _quota_err(m) for m in TTS_MODELS_FALLBACK
    ]
    with patch("generator.tts._client", return_value=fake_client):
        with pytest.raises(genai_errors.ClientError):
            render_audio(turns, api_key="FAKE")
    assert fake_client.models.generate_content.call_count == len(TTS_MODELS_FALLBACK)
