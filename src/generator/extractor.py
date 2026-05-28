"""Fetch and clean a news article from a URL."""
from __future__ import annotations

from urllib.parse import urlparse

import requests
import trafilatura

from generator.types import Article

USER_AGENT = "Mozilla/5.0 (newpodcaster personal podcast generator)"
FETCH_TIMEOUT_SECONDS = 10
MIN_BODY_LEN = 200


class ExtractionError(RuntimeError):
    pass


def extract_article(url: str) -> Article:
    try:
        html = _fetch_html(url)
    except Exception as e:  # noqa: BLE001 — re-wrap as ExtractionError
        raise ExtractionError(f"fetch failed for {url}: {e}") from e

    body = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    if len(body) < MIN_BODY_LEN:
        raise ExtractionError(
            f"body too short ({len(body)} chars) for {url}"
        )

    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title if metadata and metadata.title else "Untitled").strip()
    host = urlparse(url).hostname or ""
    source = host.removeprefix("www.")

    return Article(url=url, title=title, body=body, source=source)


def _fetch_html(url: str) -> str:
    resp = requests.get(
        url,
        timeout=FETCH_TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.text
