import json

import boto3

from generator.storage import (
    EPISODES_KEY,
    get_audio_url,
    list_episodes,
    load_seen_urls,
    mark_seen,
    save_episode,
)
from generator.types import Article


def _make_article(url: str = "https://www.bbc.com/sport/football/articles/c1") -> Article:
    return {
        "url": url,
        "title": "Test Title",
        "body": "Body paragraph one.\n\nBody paragraph two.",
        "source": "bbc.com",
    }


def test_save_episode_writes_audio_and_appends_index(s3_bucket):
    article = _make_article()
    ep = save_episode(article, b"fake-wav-bytes")

    s3 = boto3.client("s3", region_name="us-west-2")
    # audio object exists
    obj = s3.get_object(Bucket=s3_bucket, Key=ep["audio_key"])
    assert obj["Body"].read() == b"fake-wav-bytes"
    # index has one record
    index_raw = s3.get_object(Bucket=s3_bucket, Key=EPISODES_KEY)["Body"].read()
    index = json.loads(index_raw)
    assert len(index) == 1
    assert index[0]["url"] == article["url"]
    assert index[0]["id"] == ep["id"]


def test_save_episode_prepends_to_existing_index(s3_bucket):
    save_episode(_make_article("https://www.bbc.com/a/1"), b"a")
    save_episode(_make_article("https://www.bbc.com/a/2"), b"b")
    eps = list_episodes()
    assert [e["url"] for e in eps] == [
        "https://www.bbc.com/a/2",
        "https://www.bbc.com/a/1",
    ]


def test_list_episodes_empty_when_no_index(s3_bucket):
    assert list_episodes() == []


def test_get_audio_url_returns_presigned(s3_bucket):
    ep = save_episode(_make_article(), b"bytes")
    url = get_audio_url(ep)
    assert url.startswith("https://")
    assert ep["audio_key"] in url


def test_seen_urls_round_trip(s3_bucket):
    assert load_seen_urls() == set()
    mark_seen(["https://a.example/1", "https://a.example/2"])
    mark_seen(["https://a.example/2", "https://a.example/3"])
    assert load_seen_urls() == {
        "https://a.example/1",
        "https://a.example/2",
        "https://a.example/3",
    }
