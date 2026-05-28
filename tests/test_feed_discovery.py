from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from generator.feed_discovery import (
    DAILY_CAP,
    WIDE_TO_NARROW_THRESHOLD,
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
    wide_entries = [
        _entry("https://w/1", "Inside", "Wed, 27 May 2026 12:00:00 GMT"),
        _entry("https://w/2", "Inside-2", "Tue, 26 May 2026 12:00:00 GMT"),
        _entry("https://w/3", "Too old", "Sun, 24 May 2026 12:00:00 GMT"),
    ]
    with patch("generator.feed_discovery.feedparser.parse") as fp:
        fp.return_value = _fake_feedparser_parse(wide_entries)
        result = discover(now=now, seen_urls=set())
    urls = [c["url"] for c in result]
    assert "https://w/1" in urls
    assert "https://w/2" in urls
    assert "https://w/3" not in urls


def test_discover_dedups_against_seen(now):
    wide_entries = [
        _entry("https://w/1", "A", "Wed, 27 May 2026 12:00:00 GMT"),
        _entry("https://w/2", "B", "Wed, 27 May 2026 12:00:00 GMT"),
    ]
    with patch("generator.feed_discovery.feedparser.parse") as fp:
        fp.return_value = _fake_feedparser_parse(wide_entries)
        result = discover(now=now, seen_urls={"https://w/1"})
    assert [c["url"] for c in result] == ["https://w/2"]


def test_discover_caps_to_daily_limit(now):
    entries = [
        _entry(f"https://w/{i}", f"T{i}", "Wed, 27 May 2026 12:00:00 GMT")
        for i in range(20)
    ]
    with patch("generator.feed_discovery.feedparser.parse") as fp:
        fp.return_value = _fake_feedparser_parse(entries)
        result = discover(now=now, seen_urls=set())
    assert len(result) == DAILY_CAP


def test_discover_swaps_to_narrow_when_over_threshold(now):
    """If wide-net yields >10 candidates, swap to narrow feeds."""
    wide_entries = [
        _entry(f"https://wide/{i}", f"WT{i}", "Wed, 27 May 2026 12:00:00 GMT")
        for i in range(WIDE_TO_NARROW_THRESHOLD + 5)
    ]
    narrow_entries = [
        _entry("https://narrow/arsenal", "Arsenal news", "Wed, 27 May 2026 12:00:00 GMT"),
    ]

    def fake_parse(url):
        if "european" in url or "champions-league" in url:
            return _fake_feedparser_parse(wide_entries)
        return _fake_feedparser_parse(narrow_entries)

    with patch("generator.feed_discovery.feedparser.parse", side_effect=fake_parse):
        result = discover(now=now, seen_urls=set())
    assert all(c["url"].startswith("https://narrow") for c in result)


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
        result = discover(now=now, seen_urls=set())
    assert [c["url"] for c in result] == ["https://w/ok"]
