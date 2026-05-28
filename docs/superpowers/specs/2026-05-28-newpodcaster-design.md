# Newpodcaster — Design Spec (v2)

**Status:** Approved 2026-05-28 (v2 supersedes the original paste-URL design)
**Owner:** rjain1984 (personal project — no Snap data or infrastructure)

## Problem

I want to listen to BBC football news as a daily AI podcast. Every morning, the app should generate two-host NotebookLM-style episodes from the previous day's BBC Sport football articles (European + World Cup focus; Arsenal + Premier League fallback when news is heavy), capped at 5 episodes per day to stay inside free-tier AI quotas.

## Goals

- Fully automated: no clicking "generate" — I open the app and listen.
- One scheduled run per day at **09:00 PT** (Pacific) using AWS Lambda.
- Discover articles from BBC Sport RSS feeds; filter by date and topic.
- Hard cap of **5 new episodes per day** to keep API usage trivially inside free tiers.
- All-in cost target ≤ $1/month.
- Single-user personal use.

## Non-goals (v1)

- No paste-URL feature (removed from original design).
- No on-demand "Refresh" button in the UI. Debug/test via `sam local invoke` or AWS console.
- No multi-user accounts.
- No queueing of more than 5 articles for "later". If a day has more, we just drop the rest.
- No failure notifications (CloudWatch Logs only).
- No retry/resume — if a Lambda run partially fails, those articles are not marked as seen, so the next day's run will try them again.
- No support for paywalled / heavy-JS articles. BBC Sport is plain HTML; `trafilatura` is sufficient.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Viewer (frontend + app server) | Streamlit on Streamlit Community Cloud | Free, auto-deploys from GitHub, fits a single-user Python tool |
| Generator runtime | AWS Lambda (Python 3.12, 1024 MB, 5-min timeout) | Pay-per-invocation; one run/day is essentially free; user already has AWS configured |
| Schedule | EventBridge cron rule | Native AWS scheduling; cron `0 16 * * ? *` for 09:00 PDT |
| AI: script generation | Gemini 2.5 Flash (text) | Cheap, generous free tier |
| AI: speech synthesis | Gemini 2.5 Flash TTS (multi-speaker) | Single call returns two-voice dialog audio |
| Article extraction | `trafilatura` | Pure Python, works on BBC HTML |
| RSS parsing | `feedparser` | Standard, lightweight |
| Persistent storage | AWS S3 | Pennies/month |
| Secrets | AWS Secrets Manager (Lambda side); Streamlit Cloud secrets manager (viewer side) | Native to each runtime |
| Auth (viewer) | Single shared password via `st.secrets` | Community Cloud URL is public; cheap gate against curious visitors |
| Lambda deployment | AWS SAM (`template.yaml` + `sam build && sam deploy`) | Lightest tool for a single Lambda + cron + IAM |
| CI | GitHub Actions on push to `main` | `sam deploy` for the Lambda; Streamlit Cloud auto-deploys the viewer separately |

## Architecture

```
        EventBridge (cron: 09:00 PT daily)
                       │
                       ▼
        ┌──────────────────────────────┐
        │  Generator Lambda            │
        │   feed_discovery → extractor │
        │   → dialog → tts → storage   │
        └──────────────┬───────────────┘
                       │ reads/writes
                       ▼
        ┌──────────────────────────────┐
        │   AWS S3 (newpodcaster)      │
        │   audio/<id>.wav             │
        │   index/episodes.json        │
        │   index/seen_urls.json       │
        └──────────────┬───────────────┘
                       │ reads
                       ▼
        ┌──────────────────────────────┐
        │  Streamlit Cloud viewer      │
        │   - password gate            │
        │   - list episodes            │
        │   - audio player             │
        └──────────────────────────────┘

  External:
   - BBC RSS feeds (RSS over HTTPS)
   - Gemini API (text + TTS)
```

## Components

Each module is one small file with a narrow public surface.

### Generator (Lambda)

#### `lambda_handler.py`
```python
def handler(event, context) -> dict: ...
```
- Entrypoint invoked by EventBridge.
- Orchestrates: discover → for each article: extract, dialog, tts, store → log summary.
- Returns `{"generated": <count>, "skipped": <count>, "errors": <count>}` for CloudWatch visibility.
- Per-article failures are logged and counted but do not abort the run.

#### `feed_discovery.py`
```python
class Candidate(TypedDict):
    url: str
    title: str
    pub_date: str        # ISO 8601
    source_feed: str     # which BBC feed it came from

WIDE_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/european/rss.xml",
    "https://feeds.bbci.co.uk/sport/football/world_cup/rss.xml",
]
NARROW_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml",
    "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml",
]
WIDE_TO_NARROW_THRESHOLD = 10
DAILY_CAP = 5
INITIAL_FLOOR_DATE = "2026-05-25"  # one-time backfill anchor; ignored once seen_urls is non-empty
ROLLING_WINDOW_DAYS = 3

def discover(now: datetime, seen_urls: set[str]) -> list[Candidate]: ...
```
- Pulls each RSS feed with `feedparser`. Network errors per-feed are logged and the feed is skipped (others continue).
- Filters by `pub_date` to the rolling window (`now - 3 days`) on subsequent runs; on the very first run also applies the May-25 floor.
- Removes URLs already in `seen_urls`.
- If the remaining wide-feed count is `>10`, swap to `NARROW_FEEDS` (re-fetch, re-filter, re-dedup).
- Sort by `pub_date` desc, take the top `5`.
- Exact feed URLs **to be verified during implementation** — if a feed 404s, log and fall back to the next-best scope or skip that scope.

#### `extractor.py`, `dialog.py`, `tts.py`
Same as the previous version of this spec — unchanged interfaces and behavior. Brief recap:
- `extract_article(url) -> Article(url, title, body, source)` via `trafilatura`. Raises `ExtractionError`.
- `generate_dialog(article) -> list[Turn]` via Gemini 2.5 Flash text. Two hosts ("Alex", "Sam"). Returns strict-JSON-parsed list. Raises `DialogError`.
- `render_audio(turns) -> bytes` via Gemini 2.5 Flash TTS multi-speaker (host_a → "Charon", host_b → "Kore"). Returns WAV bytes. Raises `TtsError`.

#### `storage.py`
```python
class Episode(TypedDict):
    id: str          # uuid4
    url: str
    title: str
    source: str
    created_at: str  # ISO 8601 UTC
    audio_key: str

def save_episode(article: Article, audio: bytes) -> Episode: ...
def list_episodes() -> list[Episode]: ...     # newest first
def get_audio_url(ep: Episode) -> str: ...    # presigned GET, 1 hour
def load_seen_urls() -> set[str]: ...
def mark_seen(urls: Iterable[str]) -> None: ...
```
- S3 layout:
  - `audio/<episode_id>.wav` — audio file per episode
  - `index/episodes.json` — list of `Episode` records (canonical)
  - `index/seen_urls.json` — set of URLs we've already processed (success or skipped) — separate file so we can blacklist URLs the generator chose not to use without polluting `episodes.json`
- Single-writer (Lambda), so plain read-modify-write is safe.

### Viewer (Streamlit)

#### `app.py`
- Password gate using `st.secrets["app_password"]`.
- After unlock: title, last-updated timestamp (from newest episode), and a vertical list of `Episode` records (newest first).
- Each row shows: title, source feed badge, date, and an `st.audio` player pointed at the presigned URL.
- Reads `index/episodes.json` via `boto3` on each page load. Streamlit's natural rerun behavior is sufficient — no manual cache.

## Configuration

### Streamlit Cloud secrets (`.streamlit/secrets.toml`, gitignored)
```toml
app_password = "..."
aws_access_key_id = "..."           # read-only IAM user for the S3 bucket
aws_secret_access_key = "..."
aws_region = "us-west-2"
s3_bucket = "rjain-newpodcaster"
```

### Lambda configuration (via SAM template)
- Environment variables: `S3_BUCKET`, `GEMINI_SECRET_NAME`, `LOG_LEVEL`
- IAM role permissions:
  - `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on `rjain-newpodcaster/*`
  - `secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:<region>:<acct>:secret:newpodcaster/gemini_api_key*`
  - `logs:*` on its own log group (default Lambda role)
- AWS Secrets Manager entry `newpodcaster/gemini_api_key` holds the Gemini key as a JSON object `{"api_key": "..."}`

## Data flow (daily Lambda run)

1. EventBridge fires at 16:00 UTC (09:00 PDT) and invokes the Lambda.
2. Lambda calls `storage.load_seen_urls()`.
3. `feed_discovery.discover(now, seen_urls)` returns up to 5 candidates.
4. For each candidate:
   - `extractor.extract_article(url)` → `Article`
   - `dialog.generate_dialog(article)` → `list[Turn]`
   - `tts.render_audio(turns)` → `bytes`
   - `storage.save_episode(article, audio)` → `Episode` (writes WAV, appends to `episodes.json`)
   - `storage.mark_seen([url])`
   - Failures: log, mark URL as seen with a failure tag so we don't retry forever, continue to next.
5. Lambda exits, returns counters. CloudWatch Logs has the per-article detail.

User opens Streamlit app at any time → sees updated list.

## Error handling

- Per-article exceptions caught in the Lambda loop. Article is logged-and-skipped; URL is still added to `seen_urls` to avoid retry loops. This is intentional — for a personal tool, "skip and move on" is the right tradeoff.
- Feed-level errors (e.g., one RSS endpoint times out) log and continue with remaining feeds.
- If `discover` returns zero candidates, Lambda exits successfully with `generated: 0`.
- Viewer-side: if `episodes.json` doesn't exist yet (first deploy before first Lambda run), show "No episodes yet — check back after 09:00 PT."

## Testing

| Module | Approach |
|---|---|
| `feed_discovery` | Unit tests with saved RSS XML fixtures. Cover: empty feed, wide-net under threshold, wide-net over threshold → narrow swap, dedup against seen set, 5-cap. |
| `extractor` | Unit tests against saved BBC HTML fixtures + an explicit-empty-page test. |
| `dialog` | Unit tests with a mocked Gemini client. JSON parse, malformed-response handling, prompt content. |
| `tts` | Unit tests with a mocked Gemini client. Multi-speaker config correctness, byte passthrough. |
| `storage` | Unit tests using `moto` to mock S3. save/list/presigned URL + seen-URL read-modify-write. |
| `lambda_handler` | One unit test that mocks all four collaborators and verifies the orchestration (e.g., 3 candidates → 3 save_episode calls, 1 fails → still 2 saves + 3 mark_seen). |
| End-to-end | One pytest gated by `RUN_E2E=1` that hits a real BBC feed, generates 1 episode, and writes to a sandbox S3 prefix. Not in CI. |
| Viewer UI | Not unit-tested. Manual verification on the deployed URL. |

## Deployment

- **Lambda** — GitHub Actions workflow `.github/workflows/deploy-lambda.yml`:
  - Trigger: push to `main` affecting `lambda/**` or `template.yaml`
  - Steps: setup Python → `sam build` → `sam deploy --no-confirm-changeset` with creds from repo secrets
- **Viewer** — Streamlit Community Cloud auto-deploys on push to `main`. Secrets managed in the Streamlit Cloud dashboard.
- **Initial setup (one-time, manual)** — documented in README:
  1. Create S3 bucket
  2. Create IAM user for Streamlit Cloud (read-only on the bucket)
  3. Create Secrets Manager entry for Gemini key
  4. `sam deploy --guided` once to create the stack
  5. Connect the GitHub repo to Streamlit Cloud and configure secrets

## Cost estimate

| Item | Estimate |
|---|---|
| Streamlit Community Cloud | $0 |
| Lambda: 1 invocation/day × ~3 min × 1024 MB | $0 (well inside free tier; even without free tier, < $0.10/month) |
| EventBridge: 1 rule, 30 invocations/month | $0 |
| AWS Secrets Manager: 1 secret | ~$0.40/month |
| S3 storage: ~150 episodes × ~5 MB | ~$0.02/month |
| S3 GETs / data transfer (personal listening) | ~$0.05–0.20/month |
| Gemini Flash (text + multi-speaker TTS): 5 episodes/day × ~3 K chars dialog | $0 (comfortably inside free tier) |
| **Total** | **~$0.50/month** |

## Risks / open items

- **BBC RSS feed URLs**: the exact URLs in the spec are best-guess based on BBC's standard pattern (`feeds.bbci.co.uk/sport/football/<section>/rss.xml`). Implementation must verify each feed responds and contains items; if a feed 404s, fall back to scraping the corresponding section page (`https://www.bbc.com/sport/football/european`, etc.) with `trafilatura` + a list selector.
- **Gemini multi-speaker TTS free-tier eligibility**: confirm at implementation time. If the preview-tier multi-speaker model isn't on the free tier, fall back to two single-voice TTS calls and stitch with `pydub`. Same audible result; modestly more code.
- **Lambda package size**: `trafilatura` + `feedparser` + `google-generativeai` + `boto3` should fit comfortably under the 250 MB unzipped limit. If we ever bump up against it, switch to a container-image Lambda.
- **Time-zone clarity**: cron `0 16 * * ? *` is 09:00 **PDT**. Once PST (Nov–Mar) is in effect, this runs at 08:00 local. Acceptable for a personal tool, but noted here so it's not a surprise.
- **Concurrent reads**: viewer reads `episodes.json` while Lambda is writing it once a day. The write is a small overwrite, but a viewer mid-write could see a stale or partial response. Mitigation: Lambda writes to a temp key then `CopyObject` to the canonical key (atomic from the reader's POV). Cheap and simple.
