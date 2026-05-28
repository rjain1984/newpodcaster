from unittest.mock import MagicMock, patch

import pytest

from generator.tts import HOST_A_NAME, HOST_B_NAME, TtsError, render_audio


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


def test_render_audio_returns_bytes():
    turns = [
        {"speaker": "host_a", "text": "Welcome."},
        {"speaker": "host_b", "text": "Glad to be here."},
    ]
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _audio_response(b"WAV-BYTES")
    with patch("generator.tts._client", return_value=fake_client):
        audio = render_audio(turns, api_key="FAKE")
    assert audio == b"WAV-BYTES"


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
