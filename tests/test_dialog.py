import json
from unittest.mock import MagicMock, patch

import pytest

from generator.dialog import DialogError, generate_dialog
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
