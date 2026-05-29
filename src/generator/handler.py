"""Lambda entrypoint. One scheduled invocation per day."""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from google.genai import errors as genai_errors

from generator.config import load_config
from generator.dialog import generate_dialog
from generator.extractor import extract_article
from generator.feed_discovery import discover
from generator.storage import load_seen_urls, mark_seen, save_episode
from generator.tts import render_audio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Gemini free tier caps gemini-2.5-flash-tts at 3 requests/minute. Sleep
# between articles so 5 articles span >60s and stay inside the limit.
INTER_ARTICLE_SLEEP_SECONDS = 21


def handler(event, context) -> dict:
    cfg = load_config()
    seen = load_seen_urls()
    candidates = discover(now=datetime.now(UTC), seen_urls=seen)
    logger.info("discovered %d candidates", len(candidates))

    generated = 0
    errors = 0
    transient_failures = 0
    for i, cand in enumerate(candidates):
        if i > 0:
            time.sleep(INTER_ARTICLE_SLEEP_SECONDS)
        is_transient = False
        try:
            article = extract_article(cand["url"])
            turns = generate_dialog(article, api_key=cfg.gemini_api_key)
            audio = render_audio(turns, api_key=cfg.gemini_api_key)
            save_episode(article, audio)
            generated += 1
            logger.info("generated episode for %s", cand["url"])
        except (genai_errors.ClientError, genai_errors.ServerError) as e:
            # Gemini-side errors (rate limits, 5xx, etc.) are transient — don't
            # mark seen, so we can retry on the next scheduled run.
            is_transient = True
            transient_failures += 1
            errors += 1
            logger.warning(
                "transient Gemini error on %s: %s — will retry next run",
                cand["url"],
                e,
            )
        except Exception as e:  # noqa: BLE001 — permanent failures get marked seen
            errors += 1
            logger.exception("permanent failure on %s: %s", cand["url"], e)

        # Mark URL as seen only on success or permanent failure. Transient errors
        # (rate limits, service outages) leave the URL unmarked so it gets retried.
        if not is_transient:
            mark_seen([cand["url"]])

    summary = {
        "generated": generated,
        "skipped": 0,
        "errors": errors,
        "transient_failures": transient_failures,
    }
    logger.info("run summary: %s", summary)
    return summary
