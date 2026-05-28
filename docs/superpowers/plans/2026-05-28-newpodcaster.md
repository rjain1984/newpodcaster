# Newpodcaster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a working daily BBC-football AI podcast: a scheduled AWS Lambda discovers BBC Sport articles, generates two-host Gemini audio, stores it in S3, and a Streamlit Cloud viewer plays it.

**Architecture:** Two cooperating pieces. **Generator** is an AWS Lambda triggered by EventBridge at 09:00 PT daily; it fetches BBC RSS feeds (wide net of European + Champions League, narrowing to Premier League + Arsenal when >10 articles in window), caps at 5 articles/day, calls Gemini for dialog + multi-speaker TTS, and writes audio + index files to S3. **Viewer** is a tiny Streamlit app on Streamlit Community Cloud that reads `index/episodes.json` from S3 and plays audio via presigned URLs. A password gate on the viewer keeps the public URL from being abused.

**Tech Stack:** Python 3.12, AWS Lambda + EventBridge + S3 + Secrets Manager (via AWS SAM), Streamlit Community Cloud, Google Gemini 2.5 Flash (text) + Gemini 2.5 Flash Preview TTS (multi-speaker audio), `trafilatura`, `feedparser`, `boto3`, `pytest` + `moto` for tests.

---

## Repository layout (final)

```
newpodcaster/
├── app.py                          # Streamlit viewer (root for SC convention)
├── requirements.txt                # Viewer deps (root for SC convention)
├── .streamlit/
│   └── config.toml                 # viewer theme + page config
├── src/                            # SAM CodeUri root
│   ├── requirements.txt            # Lambda deps (SAM picks this up)
│   └── generator/                  # Python package — Lambda code
│       ├── __init__.py
│       ├── handler.py              # Lambda entrypoint
│       ├── feed_discovery.py       # RSS → filter → wide/narrow → cap 5
│       ├── extractor.py            # trafilatura wrapper
│       ├── dialog.py               # Gemini text → list[Turn]
│       ├── tts.py                  # Gemini multi-speaker TTS
│       ├── storage.py              # S3 read/write
│       ├── config.py               # env + Secrets Manager
│       └── types.py                # shared TypedDicts
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # shared fixtures (moto)
│   ├── fixtures/
│   │   ├── bbc_european.rss        # saved RSS for discovery tests
│   │   ├── bbc_arsenal.rss
│   │   └── bbc_article.html        # saved HTML for extractor test
│   ├── test_feed_discovery.py
│   ├── test_extractor.py
│   ├── test_dialog.py
│   ├── test_tts.py
│   ├── test_storage.py
│   └── test_handler.py
├── template.yaml                   # SAM template (CodeUri: src/)
├── samconfig.toml.example          # SAM deploy config template
├── pyproject.toml                  # pytest config (pythonpath=src) + ruff
├── Makefile                        # dev commands
├── .github/workflows/
│   └── deploy-lambda.yml           # CI/CD: sam deploy on push to main
├── docs/superpowers/...            # spec + this plan (existing)
├── README.md                       # existing
└── .gitignore                      # existing
```

**Why the `src/` layout:**
- Locally, `pyproject.toml` sets `pythonpath = ["src"]` so `pytest` can `from generator.X import Y`.
- For Lambda, `template.yaml` sets `CodeUri: src/` and `Handler: generator.handler.handler`. SAM packages `src/`'s contents into the zip, so the zip layout is `/var/task/generator/*.py + /var/task/<deps>/`. The same `from generator.X import Y` imports work.
- Streamlit Cloud still finds `app.py` and `requirements.txt` at the repo root (its convention).

---

## Task 1: Verify BBC RSS feed URLs

**Goal:** Confirm which BBC Sport football RSS feeds actually exist before any code is written. The spec lists best-guess URLs; this task verifies them.

**Files:** None (research task, but the findings get recorded in `docs/superpowers/plans/2026-05-28-newpodcaster.md` — append a "Feed verification results" subsection at the bottom of this plan after Task 17).

- [ ] **Step 1: curl each candidate feed and confirm HTTP 200 + valid RSS**

Run each in sequence (don't parallelize — output ordering matters for the notes):

```bash
for url in \
  https://feeds.bbci.co.uk/sport/football/rss.xml \
  https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml \
  https://feeds.bbci.co.uk/sport/football/european/rss.xml \
  https://feeds.bbci.co.uk/sport/football/world_cup/rss.xml \
  https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml \
; do
  printf '%s -> ' "$url"
  curl -s -o /dev/null -w "%{http_code}\n" "$url"
done
```

Expected: each line ends with `200`. Any `404` or `403` means that feed must be replaced.

- [ ] **Step 2: For each feed that returned 200, save the first 30 lines to confirm it's well-formed RSS**

```bash
curl -s https://feeds.bbci.co.uk/sport/football/european/rss.xml | head -30
```

Expected: starts with `<?xml`, contains `<rss` and `<channel>`, with `<item>` elements that have `<link>`, `<title>`, `<pubDate>`.

- [ ] **Step 3: For each 404, find the working alternative**

Common BBC patterns to try:
- `https://feeds.bbci.co.uk/sport/football/<slug>/rss.xml` where slug is one of `european`, `champions-league`, `europa-league`, `world-cup`, `internationals`
- Team slugs: `https://feeds.bbci.co.uk/sport/football/teams/<slug>/rss.xml` — Arsenal slug should be `arsenal`

If no feed works for a topic, fall back to scraping the section page with `trafilatura` later — note this in the results section.

- [ ] **Step 4: Save fixtures for tests**

```bash
mkdir -p tests/fixtures
curl -s https://feeds.bbci.co.uk/sport/football/european/rss.xml -o tests/fixtures/bbc_european.rss
curl -s https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml -o tests/fixtures/bbc_arsenal.rss
# pick one article URL from the european feed and save its HTML:
ARTICLE_URL="$(grep -oE 'https://www.bbc.com/[^<]+' tests/fixtures/bbc_european.rss | head -1)"
curl -sL -A 'Mozilla/5.0' "$ARTICLE_URL" -o tests/fixtures/bbc_article.html
ls -la tests/fixtures/
```

Expected: three non-empty files (`bbc_european.rss`, `bbc_arsenal.rss`, `bbc_article.html`).

- [ ] **Step 5: Record findings + commit fixtures**

Append a "Feed verification results" section at the bottom of this plan file recording each URL's status and chosen alternative if needed.

```bash
git add tests/fixtures/ docs/superpowers/plans/2026-05-28-newpodcaster.md
git commit -m "chore: verify BBC RSS feeds and save fixtures"
```

---

## Task 2: Project scaffolding

**Goal:** Create empty package directories, `pyproject.toml`, `Makefile`, requirements files, and `.streamlit/config.toml`. After this, `pytest` runs (and finds zero tests) and `make help` lists commands.

**Files:**
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `requirements.txt` (viewer, at repo root)
- Create: `src/generator/__init__.py`
- Create: `src/requirements.txt` (Lambda deps)
- Create: `tests/__init__.py`
- Create: `.streamlit/config.toml`

- [ ] **Step 1: Create the empty package files and Streamlit config**

```bash
mkdir -p src/generator tests .streamlit
touch src/generator/__init__.py tests/__init__.py
```

`.streamlit/config.toml`:
```toml
[theme]
base = "dark"
primaryColor = "#FF4B4B"

[server]
headless = true
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "newpodcaster"
version = "0.1.0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
pythonpath = ["src"]
addopts = "-ra -q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

- [ ] **Step 3: Write the viewer `requirements.txt`** (repo root)

```
streamlit==1.40.2
boto3==1.35.74
```

- [ ] **Step 4: Write the Lambda `requirements.txt`** at `src/requirements.txt`

(SAM's Python builder looks for `requirements.txt` at the `CodeUri` root, which we'll set to `src/`. This file is for the Lambda only — Streamlit Cloud uses the root `requirements.txt`.)

```
boto3==1.35.74
feedparser==6.0.11
trafilatura==1.12.2
google-genai==0.5.0
requests==2.32.3
```

- [ ] **Step 5: Write `Makefile`**

```makefile
.PHONY: help install test lint run-viewer sam-build sam-deploy clean

help:
	@echo "make install     - install dev deps (root + generator)"
	@echo "make test        - run pytest"
	@echo "make lint        - run ruff"
	@echo "make run-viewer  - run streamlit locally"
	@echo "make sam-build   - sam build"
	@echo "make sam-deploy  - sam deploy"

install:
	python3 -m pip install -U pip
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r src/requirements.txt
	python3 -m pip install pytest pytest-mock moto ruff

test:
	python3 -m pytest

lint:
	python3 -m ruff check .

run-viewer:
	streamlit run app.py

sam-build:
	sam build --template template.yaml

sam-deploy:
	sam deploy --no-confirm-changeset

clean:
	rm -rf .pytest_cache .aws-sam build dist *.egg-info
```

- [ ] **Step 6: Install deps and verify pytest runs**

```bash
make install
make test
```

Expected: `make install` succeeds. `make test` exits 0 with output similar to `no tests ran`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml Makefile requirements.txt src/ tests/ .streamlit/
git commit -m "chore: project scaffolding (pyproject, Makefile, deps, streamlit config)"
```

---

## Task 3: Shared types

**Goal:** Define the four `TypedDict`s used across modules so later tasks can import them.

**Files:**
- Create: `src/generator/types.py`

- [ ] **Step 1: Write `src/generator/types.py`**

```python
"""Shared data types used across the generator pipeline."""
from typing import Literal, TypedDict


class Candidate(TypedDict):
    """An article discovered from an RSS feed, not yet processed."""
    url: str
    title: str
    pub_date: str        # ISO 8601 UTC
    source_feed: str     # the feed URL it came from


class Article(TypedDict):
    """A successfully-extracted article."""
    url: str
    title: str
    body: str            # plain text, paragraphs separated by \n\n
    source: str          # e.g. "bbc.com"


class Turn(TypedDict):
    """One speaker turn in the generated dialog."""
    speaker: Literal["host_a", "host_b"]
    text: str


class Episode(TypedDict):
    """A persisted podcast episode."""
    id: str              # uuid4
    url: str
    title: str
    source: str
    created_at: str      # ISO 8601 UTC
    audio_key: str       # S3 key for the audio file
```

- [ ] **Step 2: Confirm it imports clean**

```bash
python3 -c "from generator.types import Candidate, Article, Turn, Episode; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/generator/types.py
git commit -m "feat(types): add shared TypedDicts for the generator pipeline"
```

---

## Task 4: Config loading

**Goal:** A single place where all env vars + secrets are read, so the rest of the code never touches `os.environ` directly. Easy to mock in tests.

**Files:**
- Create: `src/generator/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test** at `tests/test_config.py`

```python
import json
from unittest.mock import MagicMock, patch

from generator.config import load_config


def test_load_config_reads_env_and_fetches_gemini_secret(monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("GEMINI_SECRET_NAME", "newpodcaster/gemini_api_key")
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    fake_secret = json.dumps({"api_key": "FAKE-GEMINI-KEY"})
    fake_sm = MagicMock()
    fake_sm.get_secret_value.return_value = {"SecretString": fake_secret}

    with patch("generator.config.boto3.client", return_value=fake_sm):
        cfg = load_config()

    assert cfg.s3_bucket == "test-bucket"
    assert cfg.gemini_api_key == "FAKE-GEMINI-KEY"
    assert cfg.aws_region == "us-west-2"
    fake_sm.get_secret_value.assert_called_once_with(
        SecretId="newpodcaster/gemini_api_key"
    )
```

- [ ] **Step 2: Run test, expect fail**

```bash
python3 -m pytest tests/test_config.py -v
```

Expected: ImportError on `generator.config`.

- [ ] **Step 3: Write `src/generator/config.py`**

```python
"""Centralized configuration. Reads env vars and Secrets Manager once per cold start."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import boto3


@dataclass(frozen=True)
class Config:
    s3_bucket: str
    gemini_api_key: str
    aws_region: str


def load_config() -> Config:
    s3_bucket = os.environ["S3_BUCKET"]
    secret_name = os.environ["GEMINI_SECRET_NAME"]
    region = os.environ.get("AWS_REGION", "us-west-2")

    sm = boto3.client("secretsmanager", region_name=region)
    secret_raw = sm.get_secret_value(SecretId=secret_name)["SecretString"]
    gemini_api_key = json.loads(secret_raw)["api_key"]

    return Config(s3_bucket=s3_bucket, gemini_api_key=gemini_api_key, aws_region=region)
```

- [ ] **Step 4: Run test, expect pass**

```bash
python3 -m pytest tests/test_config.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/generator/config.py tests/test_config.py
git commit -m "feat(config): load env + Gemini key from Secrets Manager"
```

---

## Task 5: Storage layer

**Goal:** All S3 interactions live in one module. Tests use `moto` so no real AWS is hit.

**Files:**
- Create: `src/generator/storage.py`
- Create: `tests/test_storage.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
import os

import boto3
import pytest
from moto import mock_aws

BUCKET = "newpodcaster-test"


@pytest.fixture
def s3_bucket(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-west-2")
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )
        yield BUCKET
```

- [ ] **Step 2: Write the failing tests** at `tests/test_storage.py`

```python
import json
from datetime import datetime, timezone

import boto3

from generator.storage import (
    EPISODES_KEY,
    SEEN_URLS_KEY,
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
```

- [ ] **Step 3: Run tests, expect fail**

```bash
python3 -m pytest tests/test_storage.py -v
```

Expected: ImportError on `generator.storage`.

- [ ] **Step 4: Write `src/generator/storage.py`**

```python
"""S3 storage layer. Single-writer (Lambda), so plain read-modify-write is safe."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Iterable

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
        "created_at": datetime.now(timezone.utc).isoformat(),
        "audio_key": audio_key,
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
```

- [ ] **Step 5: Run tests, expect pass**

```bash
python3 -m pytest tests/test_storage.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/generator/storage.py tests/test_storage.py tests/conftest.py
git commit -m "feat(storage): S3-backed episodes index, audio, and seen-URLs"
```

---

## Task 6: Feed discovery

**Goal:** Discover BBC articles, filter by date, dedup against `seen_urls`, swap wide→narrow when >10, cap at 5.

**Files:**
- Create: `src/generator/feed_discovery.py`
- Create: `tests/test_feed_discovery.py`

- [ ] **Step 1: Write the failing tests** at `tests/test_feed_discovery.py`

```python
from datetime import datetime, timezone
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
    return datetime(2026, 5, 28, 16, 0, tzinfo=timezone.utc)  # 09:00 PDT


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
```

- [ ] **Step 2: Run tests, expect fail**

```bash
python3 -m pytest tests/test_feed_discovery.py -v
```

Expected: ImportError on `generator.feed_discovery`.

- [ ] **Step 3: Write `src/generator/feed_discovery.py`**

```python
"""Discover candidate articles from BBC Sport football RSS feeds."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser

from generator.types import Candidate

logger = logging.getLogger(__name__)

WIDE_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/european/rss.xml",
    "https://feeds.bbci.co.uk/sport/football/champions-league/rss.xml",
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
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
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
                    pub_date=pub_dt.astimezone(timezone.utc).isoformat(),
                    source_feed=feed_url,
                )
            )
    return out
```

- [ ] **Step 4: Run tests, expect pass**

```bash
python3 -m pytest tests/test_feed_discovery.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/generator/feed_discovery.py tests/test_feed_discovery.py
git commit -m "feat(discovery): BBC RSS fetch with date/dedup filter and wide/narrow swap"
```

---

## Task 7: Article extractor

**Goal:** Wrap `trafilatura` so the rest of the code gets a clean `Article` or a clear `ExtractionError`.

**Files:**
- Create: `src/generator/extractor.py`
- Create: `tests/test_extractor.py`

- [ ] **Step 1: Write the failing tests** at `tests/test_extractor.py`

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from generator.extractor import ExtractionError, extract_article

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def bbc_html() -> str:
    return (FIXTURES / "bbc_article.html").read_text(encoding="utf-8")


def test_extract_returns_article(bbc_html):
    with patch("generator.extractor._fetch_html", return_value=bbc_html):
        article = extract_article("https://www.bbc.com/sport/football/articles/test")
    assert article["url"] == "https://www.bbc.com/sport/football/articles/test"
    assert article["title"]  # non-empty
    assert len(article["body"]) >= 200  # body sanity threshold
    assert article["source"] == "bbc.com"


def test_extract_raises_when_body_too_short():
    short_html = "<html><body><p>hi</p></body></html>"
    with patch("generator.extractor._fetch_html", return_value=short_html):
        with pytest.raises(ExtractionError):
            extract_article("https://www.bbc.com/sport/football/articles/x")


def test_extract_raises_on_fetch_failure():
    with patch("generator.extractor._fetch_html", side_effect=RuntimeError("boom")):
        with pytest.raises(ExtractionError):
            extract_article("https://www.bbc.com/sport/football/articles/x")
```

- [ ] **Step 2: Run tests, expect fail**

```bash
python3 -m pytest tests/test_extractor.py -v
```

Expected: ImportError on `generator.extractor`.

- [ ] **Step 3: Write `src/generator/extractor.py`**

```python
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
    source = host.lstrip("www.")

    return Article(url=url, title=title, body=body, source=source)


def _fetch_html(url: str) -> str:
    resp = requests.get(
        url,
        timeout=FETCH_TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.text
```

- [ ] **Step 4: Run tests, expect pass**

```bash
python3 -m pytest tests/test_extractor.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/generator/extractor.py tests/test_extractor.py
git commit -m "feat(extractor): trafilatura-based article extraction with ExtractionError"
```

---

## Task 8: Dialog generation

**Goal:** Turn an `Article` into a list of `Turn` (two-host conversation). One Gemini text call with JSON-mode response.

**Files:**
- Create: `src/generator/dialog.py`
- Create: `tests/test_dialog.py`

- [ ] **Step 1: Write the failing tests** at `tests/test_dialog.py`

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from generator.dialog import DialogError, generate_dialog
from generator.types import Article


def _article() -> Article:
    return {
        "url": "https://www.bbc.com/sport/football/articles/c1",
        "title": "Arsenal beat Spurs in dramatic derby",
        "body": "Arsenal won 3-1 in north London on Sunday. " * 30,
        "source": "bbc.com",
    }


def _mock_response(payload: str) -> MagicMock:
    fake = MagicMock()
    fake.text = payload
    return fake


def test_generate_dialog_returns_turns():
    payload = json.dumps([
        {"speaker": "host_a", "text": "Welcome to today's roundup."},
        {"speaker": "host_b", "text": "Arsenal really turned it on."},
    ])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(payload)

    with patch("generator.dialog._client", return_value=fake_client):
        turns = generate_dialog(_article(), api_key="FAKE")

    assert turns == [
        {"speaker": "host_a", "text": "Welcome to today's roundup."},
        {"speaker": "host_b", "text": "Arsenal really turned it on."},
    ]


def test_generate_dialog_raises_on_bad_json():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response("not json")

    with patch("generator.dialog._client", return_value=fake_client):
        with pytest.raises(DialogError):
            generate_dialog(_article(), api_key="FAKE")


def test_generate_dialog_raises_on_wrong_schema():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(
        json.dumps([{"who": "bob", "text": "hi"}])
    )

    with patch("generator.dialog._client", return_value=fake_client):
        with pytest.raises(DialogError):
            generate_dialog(_article(), api_key="FAKE")


def test_generate_dialog_includes_article_in_prompt():
    payload = json.dumps([{"speaker": "host_a", "text": "ok"}])
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _mock_response(payload)

    with patch("generator.dialog._client", return_value=fake_client):
        generate_dialog(_article(), api_key="FAKE")

    call = fake_client.models.generate_content.call_args
    contents = call.kwargs["contents"]
    assert "Arsenal beat Spurs in dramatic derby" in contents
    assert "Arsenal won 3-1" in contents
```

- [ ] **Step 2: Run tests, expect fail**

```bash
python3 -m pytest tests/test_dialog.py -v
```

Expected: ImportError on `generator.dialog`.

- [ ] **Step 3: Write `src/generator/dialog.py`**

```python
"""Generate a two-host dialog from an article using Gemini 2.5 Flash."""
from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types as genai_types

from generator.types import Article, Turn

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You are a script writer for a short news podcast.
Two hosts named Alex (host_a) and Sam (host_b) chat about a single news article.
Tone: conversational, curious, light. Avoid jargon. Keep it accurate to the article — never invent facts.
Output strictly a JSON array of objects, each with `speaker` (either "host_a" or "host_b") and `text`.
Aim for ~1 minute of audio per 300 words of source. Most turns are 1-3 sentences.
Start with a short hook, then conversational back-and-forth, end with a one-line sign-off.
Do not include any prose outside the JSON array."""


class DialogError(RuntimeError):
    pass


def _client(api_key: str):  # extracted for easy mocking
    return genai.Client(api_key=api_key)


def generate_dialog(article: Article, api_key: str) -> list[Turn]:
    user_prompt = (
        f"Article title: {article['title']}\n\n"
        f"Article body:\n{article['body']}"
    )
    client = _client(api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )

    raw = (response.text or "").strip()
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        raise DialogError(f"could not parse Gemini response as JSON: {e}\nraw={raw!r}") from e

    if not isinstance(parsed, list) or not parsed:
        raise DialogError(f"expected non-empty JSON array, got {type(parsed).__name__}")

    turns: list[Turn] = []
    for i, item in enumerate(parsed):
        if (
            not isinstance(item, dict)
            or item.get("speaker") not in ("host_a", "host_b")
            or not isinstance(item.get("text"), str)
            or not item["text"].strip()
        ):
            raise DialogError(f"turn {i} has wrong schema: {item!r}")
        turns.append(Turn(speaker=item["speaker"], text=item["text"].strip()))
    return turns
```

- [ ] **Step 4: Run tests, expect pass**

```bash
python3 -m pytest tests/test_dialog.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/generator/dialog.py tests/test_dialog.py
git commit -m "feat(dialog): two-host conversation generation via Gemini 2.5 Flash"
```

---

## Task 9: Multi-speaker TTS

**Goal:** Take `list[Turn]` and return WAV audio bytes via Gemini 2.5 Flash Preview TTS multi-speaker.

**Files:**
- Create: `src/generator/tts.py`
- Create: `tests/test_tts.py`

- [ ] **Step 1: Write the failing tests** at `tests/test_tts.py`

```python
from unittest.mock import MagicMock, patch

import pytest

from generator.tts import HOST_A_NAME, HOST_B_NAME, TtsError, render_audio


def _audio_response(audio_bytes: bytes) -> MagicMock:
    fake_part = MagicMock()
    fake_part.inline_data.data = audio_bytes
    fake_part.inline_data.mime_type = "audio/wav"
    fake_content = MagicMock()
    fake_content.parts = [fake_part]
    fake_candidate = MagicMock()
    fake_candidate.content = fake_content
    fake_response = MagicMock()
    fake_response.candidates = [fake_candidate]
    return fake_response


def test_render_audio_returns_bytes():
    turns = [
        {"speaker": "host_a", "text": "Welcome."},
        {"speaker": "host_b", "text": "Glad to be here."},
    ]
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _audio_response(b"WAV-BYTES")
    with patch("generator.tts._client", return_value=fake_client):
        audio = render_audio(turns, api_key="FAKE")
    assert audio == b"WAV-BYTES"


def test_render_audio_passes_speaker_config():
    turns = [{"speaker": "host_a", "text": "hi"}]
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _audio_response(b"x")
    with patch("generator.tts._client", return_value=fake_client):
        render_audio(turns, api_key="FAKE")
    call = fake_client.models.generate_content.call_args
    config = call.kwargs["config"]
    speakers = config.speech_config.multi_speaker_voice_config.speaker_voice_configs
    names = [s.speaker for s in speakers]
    assert names == [HOST_A_NAME, HOST_B_NAME]


def test_render_audio_raises_when_no_audio():
    turns = [{"speaker": "host_a", "text": "hi"}]
    fake_client = MagicMock()
    empty = MagicMock()
    empty.candidates = []
    fake_client.models.generate_content.return_value = empty
    with patch("generator.tts._client", return_value=fake_client):
        with pytest.raises(TtsError):
            render_audio(turns, api_key="FAKE")


def test_render_audio_formats_input_with_speaker_names():
    turns = [
        {"speaker": "host_a", "text": "Hello."},
        {"speaker": "host_b", "text": "Hi back."},
    ]
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _audio_response(b"x")
    with patch("generator.tts._client", return_value=fake_client):
        render_audio(turns, api_key="FAKE")
    call = fake_client.models.generate_content.call_args
    contents = call.kwargs["contents"]
    assert f"{HOST_A_NAME}: Hello." in contents
    assert f"{HOST_B_NAME}: Hi back." in contents
```

- [ ] **Step 2: Run tests, expect fail**

```bash
python3 -m pytest tests/test_tts.py -v
```

Expected: ImportError on `generator.tts`.

- [ ] **Step 3: Write `src/generator/tts.py`**

```python
"""Render a list of dialog turns to multi-speaker audio via Gemini TTS."""
from __future__ import annotations

from google import genai
from google.genai import types as genai_types

from generator.types import Turn

MODEL = "gemini-2.5-flash-preview-tts"
HOST_A_NAME = "Alex"
HOST_B_NAME = "Sam"
HOST_A_VOICE = "Charon"
HOST_B_VOICE = "Kore"


class TtsError(RuntimeError):
    pass


def _client(api_key: str):
    return genai.Client(api_key=api_key)


def render_audio(turns: list[Turn], api_key: str) -> bytes:
    contents = _format_dialog(turns)
    client = _client(api_key)

    speech_config = genai_types.SpeechConfig(
        multi_speaker_voice_config=genai_types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                genai_types.SpeakerVoiceConfig(
                    speaker=HOST_A_NAME,
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=HOST_A_VOICE,
                        ),
                    ),
                ),
                genai_types.SpeakerVoiceConfig(
                    speaker=HOST_B_NAME,
                    voice_config=genai_types.VoiceConfig(
                        prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                            voice_name=HOST_B_VOICE,
                        ),
                    ),
                ),
            ]
        )
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
        ),
    )

    if not response.candidates:
        raise TtsError("Gemini returned no candidates")
    parts = response.candidates[0].content.parts
    if not parts or not getattr(parts[0], "inline_data", None):
        raise TtsError("Gemini response has no audio data")
    return parts[0].inline_data.data


def _format_dialog(turns: list[Turn]) -> str:
    lines = []
    for t in turns:
        name = HOST_A_NAME if t["speaker"] == "host_a" else HOST_B_NAME
        lines.append(f"{name}: {t['text']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests, expect pass**

```bash
python3 -m pytest tests/test_tts.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/generator/tts.py tests/test_tts.py
git commit -m "feat(tts): multi-speaker Gemini TTS rendering"
```

---

## Task 10: Lambda handler (orchestration)

**Goal:** Tie everything together. `handler(event, context)` is the Lambda entrypoint and orchestrates discover → extract → dialog → tts → store, with per-article isolation.

**Files:**
- Create: `src/generator/handler.py`
- Create: `tests/test_handler.py`

- [ ] **Step 1: Write the failing tests** at `tests/test_handler.py`

```python
from unittest.mock import MagicMock, patch

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
):
    mock_load_config.return_value = MagicMock(gemini_api_key="K")
    mock_load_seen.return_value = set()
    mock_discover.return_value = [_candidate("https://a/1"), _candidate("https://a/2")]
    mock_extract.side_effect = lambda u: _article(u)
    mock_dialog.return_value = [{"speaker": "host_a", "text": "hi"}]
    mock_tts.return_value = b"audio"
    mock_save.return_value = {"id": "x"}

    result = handler({}, None)

    assert result == {"generated": 2, "skipped": 0, "errors": 0}
    assert mock_extract.call_count == 2
    assert mock_save.call_count == 2
    # mark_seen called once per article (success or failure)
    assert mock_mark_seen.call_count == 2


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

    assert result == {"generated": 1, "skipped": 0, "errors": 1}
    assert mock_save.call_count == 1
    assert mock_mark_seen.call_count == 2  # both URLs marked seen (no retry loops)


@patch("generator.handler.load_config")
@patch("generator.handler.discover")
@patch("generator.handler.load_seen_urls")
def test_handler_empty_discovery(mock_load_seen, mock_discover, mock_load_config):
    mock_load_config.return_value = MagicMock(gemini_api_key="K")
    mock_load_seen.return_value = set()
    mock_discover.return_value = []

    result = handler({}, None)

    assert result == {"generated": 0, "skipped": 0, "errors": 0}
```

- [ ] **Step 2: Run tests, expect fail**

```bash
python3 -m pytest tests/test_handler.py -v
```

Expected: ImportError on `generator.handler`.

- [ ] **Step 3: Write `src/generator/handler.py`**

```python
"""Lambda entrypoint. One scheduled invocation per day."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

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
    candidates = discover(now=datetime.now(timezone.utc), seen_urls=seen)
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
```

- [ ] **Step 4: Run tests, expect pass**

```bash
python3 -m pytest tests/test_handler.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/generator/handler.py tests/test_handler.py
git commit -m "feat(handler): Lambda entrypoint with per-article isolation"
```

---

## Task 11: Streamlit viewer

**Goal:** Tiny viewer that lists episodes and plays them. Reads `episodes.json` from S3 every page load. Password gate at top.

**Files:**
- Create: `app.py` (repo root)

- [ ] **Step 1: Write `app.py`**

```python
"""Streamlit viewer for newpodcaster. Reads episodes from S3, plays them."""
from __future__ import annotations

import json

import boto3
import streamlit as st
from botocore.exceptions import ClientError

EPISODES_KEY = "index/episodes.json"
PRESIGNED_URL_TTL_SECONDS = 3600


@st.cache_resource
def _s3():
    return boto3.client(
        "s3",
        region_name=st.secrets["aws_region"],
        aws_access_key_id=st.secrets["aws_access_key_id"],
        aws_secret_access_key=st.secrets["aws_secret_access_key"],
    )


def _bucket() -> str:
    return st.secrets["s3_bucket"]


def _load_episodes() -> list[dict]:
    try:
        body = _s3().get_object(Bucket=_bucket(), Key=EPISODES_KEY)["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return []
        raise
    return json.loads(body)


def _presigned_url(audio_key: str) -> str:
    return _s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": audio_key},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )


def _password_gate() -> bool:
    if st.session_state.get("authed"):
        return True
    st.title("Newpodcaster")
    pwd = st.text_input("Password", type="password")
    if pwd and pwd == st.secrets["app_password"]:
        st.session_state["authed"] = True
        st.rerun()
    elif pwd:
        st.error("Wrong password.")
    return False


def main():
    st.set_page_config(page_title="Newpodcaster", page_icon="🎙️", layout="centered")
    if not _password_gate():
        return

    st.title("🎙️ Newpodcaster")
    episodes = _load_episodes()
    if not episodes:
        st.info("No episodes yet. Check back after 09:00 PT.")
        return

    st.caption(f"{len(episodes)} episodes — newest first")
    for ep in episodes:
        with st.container(border=True):
            st.subheader(ep["title"])
            st.caption(f"{ep['source']} • {ep['created_at']}")
            st.audio(_presigned_url(ep["audio_key"]))
            st.markdown(f"[Read original article]({ep['url']})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity-check syntax with `python3 -c "import ast; ast.parse(open('app.py').read())"`**

```bash
python3 -c "import ast; ast.parse(open('app.py').read())" && echo OK
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(viewer): Streamlit app to list and play episodes from S3"
```

---

## Task 12: SAM template

**Goal:** Define the Lambda + EventBridge + IAM + S3 references in a SAM template so `sam deploy` provisions everything.

**Files:**
- Create: `template.yaml`

- [ ] **Step 1: Write `template.yaml`**

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: newpodcaster — daily BBC football podcast generator

Parameters:
  S3BucketName:
    Type: String
    Description: S3 bucket for audio + index (must exist before deploy)
  GeminiSecretName:
    Type: String
    Default: newpodcaster/gemini_api_key
    Description: Secrets Manager entry holding the Gemini API key

Globals:
  Function:
    Runtime: python3.12
    Timeout: 300        # 5 minutes
    MemorySize: 1024
    Architectures:
      - arm64

Resources:
  GeneratorFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: newpodcaster-generator
      CodeUri: src/
      Handler: generator.handler.handler
      Environment:
        Variables:
          S3_BUCKET: !Ref S3BucketName
          GEMINI_SECRET_NAME: !Ref GeminiSecretName
          LOG_LEVEL: INFO
      Policies:
        - Statement:
            - Effect: Allow
              Action:
                - s3:GetObject
                - s3:PutObject
                - s3:ListBucket
              Resource:
                - !Sub arn:aws:s3:::${S3BucketName}
                - !Sub arn:aws:s3:::${S3BucketName}/*
            - Effect: Allow
              Action: secretsmanager:GetSecretValue
              Resource: !Sub arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:${GeminiSecretName}*
      Events:
        DailyCron:
          Type: Schedule
          Properties:
            # 16:00 UTC = 09:00 PDT (May–Nov) / 08:00 PST (Nov–Mar). Acceptable drift for a personal tool.
            Schedule: cron(0 16 * * ? *)
            Description: Daily newpodcaster generator run
            Enabled: true

Outputs:
  FunctionName:
    Value: !Ref GeneratorFunction
  FunctionArn:
    Value: !GetAtt GeneratorFunction.Arn
```

- [ ] **Step 2: Validate the template** (requires AWS SAM CLI installed locally)

```bash
sam validate --template template.yaml
```

Expected: `template.yaml is a valid SAM Template`.

If `sam` is not installed, skip the local validation; GitHub Actions will validate on push.

- [ ] **Step 3: Commit**

```bash
git add template.yaml
git commit -m "feat(infra): SAM template for Lambda + EventBridge cron + IAM"
```

---

## Task 13: samconfig template + dev convenience

**Goal:** A copy-to-use `samconfig.toml.example` so future deploys are one command. Real `samconfig.toml` stays gitignored.

**Files:**
- Create: `samconfig.toml.example`
- Modify: `.gitignore`

- [ ] **Step 1: Write `samconfig.toml.example`**

```toml
version = 0.1

[default.deploy.parameters]
stack_name = "newpodcaster"
region = "us-west-2"
capabilities = "CAPABILITY_IAM"
confirm_changeset = false
resolve_s3 = true
parameter_overrides = "S3BucketName=rjain-newpodcaster GeminiSecretName=newpodcaster/gemini_api_key"

[default.global.parameters]
stack_name = "newpodcaster"
```

- [ ] **Step 2: Add the real samconfig and SAM build dir to `.gitignore`**

Append to `.gitignore`:
```
# SAM
samconfig.toml
.aws-sam/
```

- [ ] **Step 3: Commit**

```bash
git add samconfig.toml.example .gitignore
git commit -m "chore: add samconfig template and gitignore SAM build dir"
```

---

## Task 14: GitHub Actions deploy workflow

**Goal:** On push to `main`, build and deploy the Lambda. The viewer auto-deploys via Streamlit Cloud's own GitHub integration — no workflow needed for it.

**Files:**
- Create: `.github/workflows/deploy-lambda.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Deploy Lambda

on:
  push:
    branches: [main]
    paths:
      - 'src/**'
      - 'template.yaml'
      - '.github/workflows/deploy-lambda.yml'
  workflow_dispatch: {}

permissions:
  contents: read
  id-token: write   # for AWS OIDC (optional; falls back to access keys)

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - uses: aws-actions/setup-sam@v2
        with:
          use-installer: true

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-west-2

      - name: SAM validate
        run: sam validate --template template.yaml

      - name: SAM build
        run: sam build --template template.yaml

      - name: SAM deploy
        run: |
          sam deploy \
            --stack-name newpodcaster \
            --region us-west-2 \
            --capabilities CAPABILITY_IAM \
            --no-confirm-changeset \
            --no-fail-on-empty-changeset \
            --resolve-s3 \
            --parameter-overrides \
              S3BucketName=rjain-newpodcaster \
              GeminiSecretName=newpodcaster/gemini_api_key
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy-lambda.yml
git commit -m "ci: deploy Lambda via SAM on push to main"
```

---

## Task 15: Local dry-run + full test pass

**Goal:** Run the whole suite, fix anything that's flaky, and do a local invocation of the handler with all externals mocked.

**Files:**
- Create: `tests/test_handler_integration.py`

- [ ] **Step 1: Write a small integration test that exercises real glue but mocked externals**

`tests/test_handler_integration.py`:
```python
"""End-to-end test of handler with all externals mocked at module boundaries.

Verifies the modules wire together correctly, not just in isolation.
"""
from unittest.mock import MagicMock, patch

import boto3
from moto import mock_aws

from generator.handler import handler

BUCKET = "newpodcaster-it"


@mock_aws
@patch("generator.handler.load_config")
@patch("generator.feed_discovery.feedparser.parse")
@patch("generator.extractor._fetch_html")
@patch("generator.dialog._client")
@patch("generator.tts._client")
def test_full_pipeline_with_mocked_externals(
    mock_tts_client,
    mock_dialog_client,
    mock_fetch_html,
    mock_feedparser,
    mock_load_config,
    monkeypatch,
):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("S3_BUCKET", BUCKET)

    s3 = boto3.client("s3", region_name="us-west-2")
    s3.create_bucket(
        Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "us-west-2"}
    )

    mock_load_config.return_value = MagicMock(gemini_api_key="FAKE", s3_bucket=BUCKET)

    fake_feed = MagicMock()
    fake_feed.entries = [
        {
            "link": "https://www.bbc.com/sport/football/articles/c1",
            "title": "Test",
            "published": "Wed, 27 May 2026 12:00:00 GMT",
        }
    ]
    fake_feed.bozo = 0
    mock_feedparser.return_value = fake_feed

    mock_fetch_html.return_value = (
        "<html><head><title>Test</title></head><body><p>"
        + ("Match recap content. " * 50)
        + "</p></body></html>"
    )

    fake_dialog_resp = MagicMock()
    fake_dialog_resp.text = '[{"speaker":"host_a","text":"hello"},{"speaker":"host_b","text":"hi"}]'
    mock_dialog_client.return_value.models.generate_content.return_value = fake_dialog_resp

    fake_part = MagicMock()
    fake_part.inline_data.data = b"WAV"
    fake_audio_resp = MagicMock()
    fake_audio_resp.candidates = [MagicMock(content=MagicMock(parts=[fake_part]))]
    mock_tts_client.return_value.models.generate_content.return_value = fake_audio_resp

    result = handler({}, None)
    assert result["generated"] == 1

    # episode landed in S3
    body = s3.get_object(Bucket=BUCKET, Key="index/episodes.json")["Body"].read()
    assert b"Test" in body
```

- [ ] **Step 2: Run the full suite**

```bash
python3 -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 3: Run lint**

```bash
python3 -m ruff check .
```

Expected: no errors. Fix anything reported.

- [ ] **Step 4: Commit**

```bash
git add tests/test_handler_integration.py
git commit -m "test: end-to-end integration test with mocked externals"
```

---

## Task 16: One-time AWS + Streamlit setup (manual)

**Goal:** Provision the AWS resources the SAM stack references and connect Streamlit Cloud. These are one-time steps documented for the operator (you).

**Files:** None (manual operator runbook). After this task, append a `## Deployment` section to `README.md` linking these steps.

- [ ] **Step 1: Create the S3 bucket**

```bash
aws s3 mb s3://rjain-newpodcaster --region us-west-2
# Block public access (everything goes through presigned URLs)
aws s3api put-public-access-block \
  --bucket rjain-newpodcaster \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

- [ ] **Step 2: Create the Gemini secret**

```bash
aws secretsmanager create-secret \
  --name newpodcaster/gemini_api_key \
  --secret-string '{"api_key":"YOUR_GEMINI_KEY_HERE"}' \
  --region us-west-2
```

Get the API key from https://aistudio.google.com/apikey (signed in to your personal Google account).

- [ ] **Step 3: Create an IAM user for the Streamlit viewer (read-only on the bucket)**

```bash
aws iam create-user --user-name newpodcaster-viewer

cat > /tmp/viewer-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::rjain-newpodcaster",
        "arn:aws:s3:::rjain-newpodcaster/*"
      ]
    }
  ]
}
EOF

aws iam put-user-policy \
  --user-name newpodcaster-viewer \
  --policy-name newpodcaster-viewer-read \
  --policy-document file:///tmp/viewer-policy.json

aws iam create-access-key --user-name newpodcaster-viewer
# Save the AccessKeyId and SecretAccessKey from the output for Streamlit Cloud.
```

- [ ] **Step 4: Create GitHub Actions deploy credentials**

Create an IAM user `newpodcaster-deployer` with the AWS-managed `AdministratorAccess` policy (or a tighter policy if preferred — SAM needs CloudFormation, Lambda, IAM, EventBridge permissions). Add its keys to the repo's GitHub Actions secrets as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.

```bash
aws iam create-user --user-name newpodcaster-deployer
aws iam attach-user-policy --user-name newpodcaster-deployer \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam create-access-key --user-name newpodcaster-deployer
```

Then in GitHub: repo → Settings → Secrets and variables → Actions → New repository secret. Add both keys.

- [ ] **Step 5: First Lambda deploy (manual, to bootstrap)**

```bash
cp samconfig.toml.example samconfig.toml
sam build --template template.yaml
sam deploy --guided   # accept defaults; confirms stack name newpodcaster
```

After this, every push to `main` redeploys via GitHub Actions.

- [ ] **Step 6: Connect Streamlit Cloud**

1. Visit https://share.streamlit.io/ and sign in with the GitHub `rjain1984` account.
2. Click "New app" → select `rjain1984/newpodcaster` → branch `main` → main file `app.py`.
3. Under "Advanced settings", paste secrets in TOML form:

```toml
app_password = "<pick a password>"
aws_access_key_id = "<from Step 3>"
aws_secret_access_key = "<from Step 3>"
aws_region = "us-west-2"
s3_bucket = "rjain-newpodcaster"
```

4. Deploy. After a minute, open the URL on phone + desktop. Enter the password; expect "No episodes yet" until the first Lambda run.

- [ ] **Step 7: Append a deployment section to README**

Add to `README.md` (after the Status section):

```markdown
## Deployment

One-time setup commands and the operator runbook live in
[`docs/superpowers/plans/2026-05-28-newpodcaster.md`](docs/superpowers/plans/2026-05-28-newpodcaster.md)
under Task 16. After initial bootstrap, `git push main` redeploys the Lambda
via GitHub Actions; Streamlit Cloud auto-redeploys the viewer.
```

Commit:
```bash
git add README.md
git commit -m "docs: add deployment pointer to README"
```

---

## Task 17: First scheduled run + verify

**Goal:** Manually invoke the Lambda once to confirm end-to-end behavior, then watch the next 09:00 PT run.

**Files:** None.

- [ ] **Step 1: Manually invoke the Lambda**

```bash
aws lambda invoke \
  --function-name newpodcaster-generator \
  --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{}' \
  /tmp/newpodcaster-out.json && cat /tmp/newpodcaster-out.json
```

Expected: JSON like `{"generated": <N>, "skipped": 0, "errors": 0}` where `N` is between 0 and 5.

- [ ] **Step 2: Tail the CloudWatch logs**

```bash
aws logs tail /aws/lambda/newpodcaster-generator --region us-west-2 --since 10m
```

Expected: log lines for discovery, per-article success/failure, and a final summary. No traceback in non-error paths.

- [ ] **Step 3: Confirm objects in S3**

```bash
aws s3 ls s3://rjain-newpodcaster/ --recursive
```

Expected: `audio/<uuid>.wav` files plus `index/episodes.json` and `index/seen_urls.json`.

- [ ] **Step 4: Open the Streamlit app**

Visit the Streamlit Cloud URL. Enter the password. Confirm at least one episode appears with a working audio player.

- [ ] **Step 5: Verify the cron is enabled**

```bash
aws events list-rules --region us-west-2 \
  | python3 -c "import json,sys; print([r['Name'] for r in json.load(sys.stdin)['Rules'] if 'newpodcaster' in r['Name']])"
aws events list-targets-by-rule --region us-west-2 \
  --rule "$(aws events list-rules --region us-west-2 --query 'Rules[?contains(Name, `newpodcaster`)].Name | [0]' --output text)"
```

Expected: at least one rule, state ENABLED, target pointing at the Lambda.

- [ ] **Step 6: Wait for and verify the next scheduled run**

At 09:00 PT the next day, re-run Step 3 (S3 ls) and confirm new audio files. If counts didn't change, check CloudWatch logs for that run.

- [ ] **Step 7: Mark the rollout complete**

Append a "Production rollout" section at the bottom of this plan file noting the first successful scheduled-run timestamp and any anomalies seen. Commit.

```bash
git add docs/superpowers/plans/2026-05-28-newpodcaster.md
git commit -m "docs(rollout): record first successful scheduled run"
```

---

## Feed verification results

Verified on 2026-05-28. All curls run from macOS (zsh) against `feeds.bbci.co.uk`.

| URL | HTTP status | Notes |
|---|---|---|
| `https://feeds.bbci.co.uk/sport/football/rss.xml` | 200 | Valid RSS 2.0, well-formed |
| `https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml` | 200 | Valid RSS 2.0, well-formed |
| `https://feeds.bbci.co.uk/sport/football/european/rss.xml` | 200 | Valid RSS 2.0, well-formed — used as `bbc_european.rss` fixture |
| `https://feeds.bbci.co.uk/sport/football/world_cup/rss.xml` | **404** | BBC removed this feed; replaced (see below) |
| `https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml` | 200 | Valid RSS 2.0, well-formed — used as `bbc_arsenal.rss` fixture |

**Replacement for `world_cup` (404):** Tried alternate slugs:
- `https://feeds.bbci.co.uk/sport/football/champions-league/rss.xml` → **200** (valid RSS, 20+ items)
- `https://feeds.bbci.co.uk/sport/football/europa-league/rss.xml` → **200** (valid RSS, 20+ items)

**Chosen alternative:** Replace `world_cup` with `champions-league` in `WIDE_FEEDS` in `src/generator/feed_discovery.py`. Champions League is the most prominent European club competition, aligns with the project's European football focus, and BBC actively maintains the feed. The `europa-league` feed is available as a fallback if needed.

**Fixture files saved:**
- `tests/fixtures/bbc_european.rss` — live content fetched 2026-05-28 (17 KB)
- `tests/fixtures/bbc_arsenal.rss` — live content fetched 2026-05-28 (14 KB)
- `tests/fixtures/bbc_article.html` — synthetic fixture based on real article metadata from the european feed (article: "How much prize money have Premier League teams earned in Europe?", URL: `https://www.bbc.com/sport/football/articles/c3d2yd99pn8o`). The BBC article HTML could not be fetched directly (Claude Code network policy blocks `www.bbc.com`), so a semantically equivalent HTML document was constructed with >200 chars of extractable body text sufficient for the `trafilatura` extractor test.

## Production rollout

_(Filled in by Task 17.)_
