"""S3 storage layer. Single-writer (Lambda), so plain read-modify-write is safe."""
from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from generator.types import Article, Episode

EPISODES_KEY = "index/episodes.json"
SEEN_URLS_KEY = "index/seen_urls.json"
AUDIO_PREFIX = "audio/"
PRESIGNED_URL_TTL_SECONDS = 3600  # 1 hour


def _s3():
    region = os.environ.get("AWS_REGION", "us-west-2")
    return boto3.client("s3", region_name=region)


def _bucket() -> str:
    return os.environ["S3_BUCKET"]


def _get_json(key: str, default):
    s3 = _s3()
    try:
        body = s3.get_object(Bucket=_bucket(), Key=key)["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return default
        raise
    return json.loads(body)


def _put_json(key: str, value) -> None:
    _s3().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=json.dumps(value).encode("utf-8"),
        ContentType="application/json",
    )


def save_episode(article: Article, audio: bytes) -> Episode:
    episode_id = str(uuid.uuid4())
    audio_key = f"{AUDIO_PREFIX}{episode_id}.wav"
    _s3().put_object(
        Bucket=_bucket(),
        Key=audio_key,
        Body=audio,
        ContentType="audio/wav",
    )
    episode: Episode = {
        "id": episode_id,
        "url": article["url"],
        "title": article["title"],
        "source": article["source"],
        "created_at": datetime.now(UTC).isoformat(),
        "audio_key": audio_key,
        "image_url": article.get("image_url"),
    }
    existing = _get_json(EPISODES_KEY, default=[])
    existing.insert(0, episode)  # newest first
    _put_json(EPISODES_KEY, existing)
    return episode


def list_episodes() -> list[Episode]:
    return _get_json(EPISODES_KEY, default=[])


def get_audio_url(ep: Episode) -> str:
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": ep["audio_key"]},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )


def load_seen_urls() -> set[str]:
    return set(_get_json(SEEN_URLS_KEY, default=[]))


def mark_seen(urls: Iterable[str]) -> None:
    current = load_seen_urls()
    current.update(urls)
    _put_json(SEEN_URLS_KEY, sorted(current))
