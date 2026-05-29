import json
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from generator.dialog import (
    SYSTEM_PROMPT_EN,
    SYSTEM_PROMPT_HINGLISH,
    TEXT_MODELS_FALLBACK,
    DialogError,
    generate_dialog,
)
from generator.types import Article


def _article() -> Article:
    return {
        "url": "https://www.bbc.com/sport/football/articles/c1",
        "title": "Arsenal beat Spurs in dramatic derby",
        "body": "Arsenal won 3-1 in north London on Sunday. " * 30,
        "source": "bbc.com",
    }


def _mock_response(payload: str) -> MagicMock:
    fake = MagicMock()
    fake.text = payload
    return fake


def test_generate_dialog_returns_turns():
    payload = json.dumps([
        {"speaker": "host_a", "text": "Welcome to today's roundup."},
        {"speaker": "host_b", "text": "Arsenal really turned it on."},
    ])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(payload)

    with patch("generator.dialog._client", return_value=fake_client):
        turns = generate_dialog(_article(), api_key="FAKE")

    assert turns == [
        {"speaker": "host_a", "text": "Welcome to today's roundup."},
        {"speaker": "host_b", "text": "Arsenal really turned it on."},
    ]


def test_generate_dialog_raises_on_bad_json():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response("not json")

    with patch("generator.dialog._client", return_value=fake_client):
        with pytest.raises(DialogError):
            generate_dialog(_article(), api_key="FAKE")


def test_generate_dialog_raises_on_wrong_schema():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(
        json.dumps([{"who": "bob", "text": "hi"}])
    )

    with patch("generator.dialog._client", return_value=fake_client):
        with pytest.raises(DialogError):
            generate_dialog(_article(), api_key="FAKE")


def test_generate_dialog_includes_article_in_prompt():
    payload = json.dumps([{"speaker": "host_a", "text": "ok"}])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(payload)

    with patch("generator.dialog._client", return_value=fake_client):
        generate_dialog(_article(), api_key="FAKE")

    call = fake_client.models.generate_content.call_args
    contents = call.kwargs["contents"]
    assert "Arsenal beat Spurs in dramatic derby" in contents
    assert "Arsenal won 3-1" in contents


def test_generate_dialog_uses_english_prompt_by_default():
    """When no topic is given, the English system prompt is used."""
    payload = json.dumps([{"speaker": "host_a", "text": "ok"}])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(payload)
    with patch("generator.dialog._client", return_value=fake_client):
        generate_dialog(_article(), api_key="FAKE")
    call = fake_client.models.generate_content.call_args
    assert call.kwargs["config"].system_instruction == SYSTEM_PROMPT_EN


def test_generate_dialog_uses_hinglish_prompt_for_hindi_topic():
    """When topic='hindi', the Hinglish system prompt is used."""
    payload = json.dumps([{"speaker": "host_a", "text": "ok"}])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(payload)
    with patch("generator.dialog._client", return_value=fake_client):
        generate_dialog(_article(), api_key="FAKE", topic="hindi")
    call = fake_client.models.generate_content.call_args
    assert call.kwargs["config"].system_instruction == SYSTEM_PROMPT_HINGLISH


def test_generate_dialog_non_hindi_topic_still_uses_english():
    """Any topic other than 'hindi' uses the English prompt."""
    payload = json.dumps([{"speaker": "host_a", "text": "ok"}])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(payload)
    with patch("generator.dialog._client", return_value=fake_client):
        generate_dialog(_article(), api_key="FAKE", topic="f1")
    call = fake_client.models.generate_content.call_args
    assert call.kwargs["config"].system_instruction == SYSTEM_PROMPT_EN


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


def test_generate_dialog_falls_through_to_next_model_on_quota():
    """When the first model 429s, try the next one in TEXT_MODELS_FALLBACK."""
    payload = json.dumps([{"speaker": "host_a", "text": "hi"}])
    fake_client = MagicMock()
    # First call 429s, second call succeeds.
    fake_client.models.generate_content.side_effect = [
        _quota_err(TEXT_MODELS_FALLBACK[0]),
        _mock_response(payload),
    ]
    with patch("generator.dialog._client", return_value=fake_client):
        turns = generate_dialog(_article(), api_key="FAKE")

    assert turns == [{"speaker": "host_a", "text": "hi"}]
    assert fake_client.models.generate_content.call_count == 2
    # Confirm we used the fallback model on the 2nd call
    second_call = fake_client.models.generate_content.call_args_list[1]
    assert second_call.kwargs["model"] == TEXT_MODELS_FALLBACK[1]


def test_generate_dialog_falls_through_on_model_not_found():
    """If a model returns 404 (not available to this key), try the next."""
    payload = json.dumps([{"speaker": "host_a", "text": "hi"}])
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        _model_not_found_err(TEXT_MODELS_FALLBACK[0]),
        _mock_response(payload),
    ]
    with patch("generator.dialog._client", return_value=fake_client):
        turns = generate_dialog(_article(), api_key="FAKE")
    assert turns == [{"speaker": "host_a", "text": "hi"}]


def test_generate_dialog_reraises_last_429_when_all_models_exhausted():
    """If every fallback model returns 429, propagate the last 429 so the
    handler treats it as transient and the URL is not marked seen."""
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = [
        _quota_err(m) for m in TEXT_MODELS_FALLBACK
    ]
    with patch("generator.dialog._client", return_value=fake_client):
        with pytest.raises(genai_errors.ClientError):
            generate_dialog(_article(), api_key="FAKE")
    # All fallback models were tried before giving up
    assert fake_client.models.generate_content.call_count == len(TEXT_MODELS_FALLBACK)
