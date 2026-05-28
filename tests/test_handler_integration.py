"""End-to-end test of handler with all externals mocked at module boundaries.

Verifies the modules wire together correctly, not just in isolation.
"""
from unittest.mock import MagicMock, patch

import boto3
from moto import mock_aws

from generator.handler import handler

BUCKET = "newpodcaster-it"


@mock_aws
@patch("generator.handler.load_config")
@patch("generator.feed_discovery.feedparser.parse")
@patch("generator.extractor._fetch_html")
@patch("generator.dialog._client")
@patch("generator.tts._client")
def test_full_pipeline_with_mocked_externals(
    mock_tts_client,
    mock_dialog_client,
    mock_fetch_html,
    mock_feedparser,
    mock_load_config,
    monkeypatch,
):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("S3_BUCKET", BUCKET)

    s3 = boto3.client("s3", region_name="us-west-2")
    s3.create_bucket(
        Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "us-west-2"}
    )

    mock_load_config.return_value = MagicMock(gemini_api_key="FAKE", s3_bucket=BUCKET)

    fake_feed = MagicMock()
    fake_feed.entries = [
        {
            "link": "https://www.bbc.com/sport/football/articles/c1",
            "title": "Test",
            "published": "Wed, 27 May 2026 12:00:00 GMT",
        }
    ]
    fake_feed.bozo = 0
    mock_feedparser.return_value = fake_feed

    mock_fetch_html.return_value = (
        "<html><head><title>Test</title></head><body><p>"
        + ("Match recap content. " * 50)
        + "</p></body></html>"
    )

    fake_dialog_resp = MagicMock()
    fake_dialog_resp.text = '[{"speaker":"host_a","text":"hello"},{"speaker":"host_b","text":"hi"}]'
    mock_dialog_client.return_value.models.generate_content.return_value = fake_dialog_resp

    fake_part = MagicMock()
    fake_part.inline_data.data = b"WAV"
    fake_audio_resp = MagicMock()
    fake_audio_resp.candidates = [MagicMock(content=MagicMock(parts=[fake_part]))]
    mock_tts_client.return_value.models.generate_content.return_value = fake_audio_resp

    result = handler({}, None)
    assert result["generated"] == 1

    # episode landed in S3
    body = s3.get_object(Bucket=BUCKET, Key="index/episodes.json")["Body"].read()
    assert b"Test" in body
