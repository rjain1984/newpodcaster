from unittest.mock import MagicMock, patch

from google.genai import errors as genai_errors

from generator.handler import handler
from generator.types import Article, Candidate


def _candidate(url: str) -> Candidate:
    return {
        "url": url,
        "title": "T",
        "pub_date": "2026-05-27T12:00:00+00:00",
        "source_feed": "https://feeds.bbci.co.uk/sport/football/european/rss.xml",
    }


def _article(url: str) -> Article:
    return {"url": url, "title": "T", "body": "b" * 300, "source": "bbc.com"}


@patch("generator.handler.time.sleep")
@patch("generator.handler.load_config")
@patch("generator.handler.discover")
@patch("generator.handler.extract_article")
@patch("generator.handler.generate_dialog")
@patch("generator.handler.render_audio")
@patch("generator.handler.save_episode")
@patch("generator.handler.mark_seen")
@patch("generator.handler.load_seen_urls")
def test_handler_happy_path(
    mock_load_seen,
    mock_mark_seen,
    mock_save,
    mock_tts,
    mock_dialog,
    mock_extract,
    mock_discover,
    mock_load_config,
    mock_sleep,
):
    mock_load_config.return_value = MagicMock(gemini_api_key="K")
    mock_load_seen.return_value = set()
    mock_discover.return_value = [_candidate("https://a/1"), _candidate("https://a/2")]
    mock_extract.side_effect = lambda u: _article(u)
    mock_dialog.return_value = [{"speaker": "host_a", "text": "hi"}]
    mock_tts.return_value = b"audio"
    mock_save.return_value = {"id": "x"}

    result = handler({}, None)

    assert result == {"generated": 2, "skipped": 0, "errors": 0, "transient_failures": 0}
    assert mock_extract.call_count == 2
    assert mock_save.call_count == 2
    # mark_seen called once per article (success or permanent failure)
    assert mock_mark_seen.call_count == 2
    # sleep called once (between articles 1 and 2)
    assert mock_sleep.call_count == 1


@patch("generator.handler.time.sleep")
@patch("generator.handler.load_config")
@patch("generator.handler.discover")
@patch("generator.handler.extract_article")
@patch("generator.handler.generate_dialog")
@patch("generator.handler.render_audio")
@patch("generator.handler.save_episode")
@patch("generator.handler.mark_seen")
@patch("generator.handler.load_seen_urls")
def test_handler_isolates_per_article_failure(
    mock_load_seen,
    mock_mark_seen,
    mock_save,
    mock_tts,
    mock_dialog,
    mock_extract,
    mock_discover,
    mock_load_config,
    mock_sleep,
):
    mock_load_config.return_value = MagicMock(gemini_api_key="K")
    mock_load_seen.return_value = set()
    mock_discover.return_value = [_candidate("https://a/1"), _candidate("https://a/2")]
    # first article fails on extract; second succeeds end-to-end
    mock_extract.side_effect = [RuntimeError("boom"), _article("https://a/2")]
    mock_dialog.return_value = [{"speaker": "host_a", "text": "hi"}]
    mock_tts.return_value = b"audio"
    mock_save.return_value = {"id": "x"}

    result = handler({}, None)

    assert result == {"generated": 1, "skipped": 0, "errors": 1, "transient_failures": 0}
    assert mock_save.call_count == 1
    # both URLs marked seen — first was a permanent failure (RuntimeError), not
    # a Gemini ClientError/ServerError, so it's still marked seen
    assert mock_mark_seen.call_count == 2


@patch("generator.handler.time.sleep")
@patch("generator.handler.load_config")
@patch("generator.handler.discover")
@patch("generator.handler.extract_article")
@patch("generator.handler.generate_dialog")
@patch("generator.handler.render_audio")
@patch("generator.handler.save_episode")
@patch("generator.handler.mark_seen")
@patch("generator.handler.load_seen_urls")
def test_handler_transient_gemini_error_does_not_mark_seen(
    mock_load_seen,
    mock_mark_seen,
    mock_save,
    mock_tts,
    mock_dialog,
    mock_extract,
    mock_discover,
    mock_load_config,
    mock_sleep,
):
    """A rate-limit / server error from Gemini must NOT mark the URL seen,
    so the article can be retried on the next scheduled run."""
    mock_load_config.return_value = MagicMock(gemini_api_key="K")
    mock_load_seen.return_value = set()
    mock_discover.return_value = [_candidate("https://a/1"), _candidate("https://a/2")]
    mock_extract.side_effect = lambda u: _article(u)
    # Article 1 fails with a Gemini 429; article 2 succeeds end-to-end
    rate_limit = genai_errors.ClientError(
        429, {"error": {"code": 429, "message": "RESOURCE_EXHAUSTED"}}, None
    )
    mock_dialog.side_effect = [rate_limit, [{"speaker": "host_a", "text": "hi"}]]
    mock_tts.return_value = b"audio"
    mock_save.return_value = {"id": "x"}

    result = handler({}, None)

    assert result == {
        "generated": 1,
        "skipped": 0,
        "errors": 1,
        "transient_failures": 1,
    }
    assert mock_save.call_count == 1
    # Only the SUCCESSFUL URL was marked seen; the rate-limited one is left
    # unmarked so the next run will retry it.
    assert mock_mark_seen.call_count == 1
    mock_mark_seen.assert_called_once_with(["https://a/2"])


@patch("generator.handler.load_config")
@patch("generator.handler.discover")
@patch("generator.handler.load_seen_urls")
def test_handler_empty_discovery(mock_load_seen, mock_discover, mock_load_config):
    mock_load_config.return_value = MagicMock(gemini_api_key="K")
    mock_load_seen.return_value = set()
    mock_discover.return_value = []

    result = handler({}, None)

    assert result == {"generated": 0, "skipped": 0, "errors": 0, "transient_failures": 0}
