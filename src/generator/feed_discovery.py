"""Discover candidate articles from BBC Sport football RSS feeds."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import feedparser

from generator.types import Candidate

logger = logging.getLogger(__name__)

WIDE_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/european/rss.xml",
    "https://feeds.bbci.co.uk/sport/football/champions-league/rss.xml",
    "https://feeds.bbci.co.uk/sport/formula1/rss.xml",
    "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml",
]
NARROW_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml",
    "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml",
]
WIDE_TO_NARROW_THRESHOLD = 10
DAILY_CAP = 5
ROLLING_WINDOW_DAYS = 3


def discover(now: datetime, seen_urls: set[str]) -> list[Candidate]:
    """Pull wide feeds; if too many, swap to narrow feeds; cap to DAILY_CAP."""
    candidates = _fetch_and_filter(WIDE_FEEDS, now, seen_urls)
    if len(candidates) > WIDE_TO_NARROW_THRESHOLD:
        logger.info(
            "Wide net returned %d > %d; switching to narrow feeds",
            len(candidates),
            WIDE_TO_NARROW_THRESHOLD,
        )
        candidates = _fetch_and_filter(NARROW_FEEDS, now, seen_urls)
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
