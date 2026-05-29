"""Discover candidate articles from BBC RSS feeds, grouped by topic."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import feedparser

from generator.types import Candidate

logger = logging.getLogger(__name__)

# Topic groups. Lambda runs one topic per invocation; the viewer shows one tab
# per topic. Add more topics by appending to this dict and to the viewer's tab
# list.
TOPIC_FEEDS: dict[str, list[str]] = {
    "football": [
        "https://feeds.bbci.co.uk/sport/football/european/rss.xml",
        "https://feeds.bbci.co.uk/sport/football/champions-league/rss.xml",
        "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml",
        "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml",
    ],
    "f1": [
        "https://feeds.bbci.co.uk/sport/formula1/rss.xml",
    ],
    "india": [
        "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml",
    ],
    "hindi": [
        # BBC's Hindi service. Articles are in Devanagari; the dialog generator
        # turns them into natural Hinglish (Hindi + English code-mixing), not
        # formal literary Hindi. See dialog.py SYSTEM_PROMPT_HINGLISH.
        "https://feeds.bbci.co.uk/hindi/rss.xml",
    ],
}
DEFAULT_TOPIC = "football"
DAILY_CAP = 5
ROLLING_WINDOW_DAYS = 3


def discover(
    now: datetime,
    seen_urls: set[str],
    topic: str = DEFAULT_TOPIC,
) -> list[Candidate]:
    """Pull RSS feeds for a single topic; cap to DAILY_CAP newest items."""
    feeds = TOPIC_FEEDS.get(topic)
    if not feeds:
        logger.warning("Unknown topic %r; falling back to %s", topic, DEFAULT_TOPIC)
        feeds = TOPIC_FEEDS[DEFAULT_TOPIC]
    candidates = _fetch_and_filter(feeds, now, seen_urls)
    candidates.sort(key=lambda c: c["pub_date"], reverse=True)
    return candidates[:DAILY_CAP]


def _fetch_and_filter(
    feeds: list[str], now: datetime, seen_urls: set[str]
) -> list[Candidate]:
    cutoff = now - timedelta(days=ROLLING_WINDOW_DAYS)
    out: list[Candidate] = []
    seen_in_this_run: set[str] = set()  # also dedup across feeds within one run
    for feed_url in feeds:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:  # noqa: BLE001 — per-feed isolation is intentional
            logger.warning("Feed fetch failed for %s: %s", feed_url, e)
            continue
        for entry in parsed.entries:
            url = entry.get("link") if isinstance(entry, dict) else getattr(entry, "link", None)
            title = entry.get("title") if isinstance(entry, dict) else getattr(entry, "title", None)
            pub_raw = (
                entry.get("published")
                if isinstance(entry, dict)
                else getattr(entry, "published", None)
            )
            if not url or not title or not pub_raw:
                continue
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                continue
            if pub_dt < cutoff:
                continue
            if url in seen_urls or url in seen_in_this_run:
                continue
            seen_in_this_run.add(url)
            out.append(
                Candidate(
                    url=url,
                    title=title,
                    pub_date=pub_dt.astimezone(UTC).isoformat(),
                    source_feed=feed_url,
                )
            )
    return out
