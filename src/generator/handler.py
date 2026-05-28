"""Lambda entrypoint. One scheduled invocation per day."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from generator.config import load_config
from generator.dialog import generate_dialog
from generator.extractor import extract_article
from generator.feed_discovery import discover
from generator.storage import load_seen_urls, mark_seen, save_episode
from generator.tts import render_audio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def handler(event, context) -> dict:
    cfg = load_config()
    seen = load_seen_urls()
    candidates = discover(now=datetime.now(UTC), seen_urls=seen)
    logger.info("discovered %d candidates", len(candidates))

    generated = 0
    errors = 0
    for cand in candidates:
        try:
            article = extract_article(cand["url"])
            turns = generate_dialog(article, api_key=cfg.gemini_api_key)
            audio = render_audio(turns, api_key=cfg.gemini_api_key)
            save_episode(article, audio)
            generated += 1
            logger.info("generated episode for %s", cand["url"])
        except Exception as e:  # noqa: BLE001 — per-article isolation is intentional
            errors += 1
            logger.exception("failed on %s: %s", cand["url"], e)
        finally:
            # mark seen even on failure to avoid retry loops on permanently bad URLs
            mark_seen([cand["url"]])

    summary = {"generated": generated, "skipped": 0, "errors": errors}
    logger.info("run summary: %s", summary)
    return summary
