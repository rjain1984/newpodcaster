from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from generator.feed_discovery import (
    DAILY_CAP,
    TOPIC_FEEDS,
    discover,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_feedparser_parse(items):
    """Helper to build a fake feedparser.FeedParserDict-like object."""

    class _Item(dict):
        def __getattr__(self, k):
            return self[k]

    class _Result:
        def __init__(self, items):
            self.entries = [_Item(i) for i in items]
            self.bozo = 0

    return _Result(items)


def _entry(url, title, pub):
    return {"link": url, "title": title, "published": pub}


@pytest.fixture
def now():
    return datetime(2026, 5, 28, 16, 0, tzinfo=UTC)  # 09:00 PDT


def test_discover_returns_candidates_inside_window(now):
    """Articles inside the 3-day window are kept; older ones are dropped."""
    entries = [
        _entry("https://w/1", "Inside", "Wed, 27 May 2026 12:00:00 GMT"),
        _entry("https://w/2", "Inside-2", "Tue, 26 May 2026 12:00:00 GMT"),
        _entry("https://w/3", "Too old", "Sun, 24 May 2026 12:00:00 GMT"),
    ]
    with patch("generator.feed_discovery.feedparser.parse") as fp:
        fp.return_value = _fake_feedparser_parse(entries)
        result = discover(now=now, seen_urls=set(), topic="football")
    urls = [c["url"] for c in result]
    assert "https://w/1" in urls
    assert "https://w/2" in urls
    assert "https://w/3" not in urls


def test_discover_dedups_against_seen(now):
    entries = [
        _entry("https://w/1", "A", "Wed, 27 May 2026 12:00:00 GMT"),
        _entry("https://w/2", "B", "Wed, 27 May 2026 12:00:00 GMT"),
    ]
    with patch("generator.feed_discovery.feedparser.parse") as fp:
        fp.return_value = _fake_feedparser_parse(entries)
        result = discover(now=now, seen_urls={"https://w/1"}, topic="football")
    assert [c["url"] for c in result] == ["https://w/2"]


def test_discover_caps_to_daily_limit(now):
    entries = [
        _entry(f"https://w/{i}", f"T{i}", "Wed, 27 May 2026 12:00:00 GMT")
        for i in range(20)
    ]
    with patch("generator.feed_discovery.feedparser.parse") as fp:
        fp.return_value = _fake_feedparser_parse(entries)
        result = discover(now=now, seen_urls=set(), topic="football")
    assert len(result) == DAILY_CAP


def test_discover_uses_only_feeds_for_requested_topic(now):
    """An f1-topic request must only hit f1 feeds; a football request only football feeds."""
    f1_entry = [_entry("https://f1/x", "F1 news", "Wed, 27 May 2026 12:00:00 GMT")]
    football_entry = [_entry("https://fb/x", "FB news", "Wed, 27 May 2026 12:00:00 GMT")]
    india_entry = [_entry("https://in/x", "IN news", "Wed, 27 May 2026 12:00:00 GMT")]

    def fake_parse(url):
        if "formula1" in url:
            return _fake_feedparser_parse(f1_entry)
        if "/india/" in url:
            return _fake_feedparser_parse(india_entry)
        return _fake_feedparser_parse(football_entry)

    with patch("generator.feed_discovery.feedparser.parse", side_effect=fake_parse) as fp:
        result = discover(now=now, seen_urls=set(), topic="f1")
        assert [c["url"] for c in result] == ["https://f1/x"]
        # Only F1 feed should have been queried
        called_urls = [call.args[0] for call in fp.call_args_list]
        assert all("formula1" in u for u in called_urls)
        assert len(called_urls) == len(TOPIC_FEEDS["f1"])


def test_discover_handles_feed_error(now):
    """If one feed fails, others continue."""
    good = [_entry("https://w/ok", "ok", "Wed, 27 May 2026 12:00:00 GMT")]

    call_count = {"n": 0}

    def fake_parse(url):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("network down")
        return _fake_feedparser_parse(good)

    with patch("generator.feed_discovery.feedparser.parse", side_effect=fake_parse):
        result = discover(now=now, seen_urls=set(), topic="football")
    # Football has 4 feeds: first fails, remaining 3 succeed
    assert [c["url"] for c in result] == ["https://w/ok"]


def test_discover_unknown_topic_falls_back_to_default(now):
    """If an unknown topic is passed, fall back to the default topic instead of crashing."""
    entries = [_entry("https://w/x", "fallback", "Wed, 27 May 2026 12:00:00 GMT")]
    with patch("generator.feed_discovery.feedparser.parse") as fp:
        fp.return_value = _fake_feedparser_parse(entries)
        result = discover(now=now, seen_urls=set(), topic="completely-made-up-topic")
    # Should still return candidates from the fallback (football) feeds
    assert len(result) > 0
