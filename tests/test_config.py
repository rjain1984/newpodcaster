import json
from unittest.mock import MagicMock, patch

from generator.config import load_config


def test_load_config_reads_env_and_fetches_gemini_secret(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("GEMINI_SECRET_NAME", "newpodcaster/gemini_api_key")
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    fake_secret = json.dumps({"api_key": "FAKE-GEMINI-KEY"})
    fake_sm = MagicMock()
    fake_sm.get_secret_value.return_value = {"SecretString": fake_secret}

    with patch("generator.config.boto3.client", return_value=fake_sm):
        cfg = load_config()

    assert cfg.s3_bucket == "test-bucket"
    assert cfg.gemini_api_key == "FAKE-GEMINI-KEY"
    assert cfg.aws_region == "us-west-2"
    fake_sm.get_secret_value.assert_called_once_with(
        SecretId="newpodcaster/gemini_api_key"
    )
