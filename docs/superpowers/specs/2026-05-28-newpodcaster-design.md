# News Podcast — Design Spec

**Status:** Approved 2026-05-28
**Owner:** rjain@snapchat.com (personal project — no Snap data or infrastructure)

## Problem

I want to listen to news articles instead of reading them. Given a URL to a news article (e.g. a BBC story), the app should produce a short two-host "podcast" of that article and let me listen on my phone.

## Goals

- Paste a URL → get a NotebookLM-style two-host conversation about the article in a few minutes.
- Accessible from my phone via a public web URL.
- Past episodes are saved so I can re-listen without paying to regenerate.
- Lowest reasonable cost — target $0–$5/month all-in.
- Personal use only. Single user.

## Non-goals (v1)

- No multi-user accounts.
- No queue / batch generation.
- No download button (Streamlit's audio widget already lets the browser save the file).
- No iOS share-sheet or Shortcut integration. May add later.
- No retry / resume logic on failure. User clicks again.
- No support for paywalled or heavily JavaScript-rendered articles. If `trafilatura` cannot extract text, the user gets a clear error and picks a different URL. A Jina Reader fallback can be added later if this becomes annoying.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Frontend & app server | Streamlit on Streamlit Community Cloud | Free hosting, auto-deploys from GitHub, fits a single-user Python tool |
| AI: script generation | Gemini 2.5 Flash (text) | Cheap, generous free tier |
| AI: speech synthesis | Gemini 2.5 Flash TTS (multi-speaker) | One API call returns two-voice dialog audio — purpose-built for this use case |
| Article extraction | `trafilatura` | Pure Python, deterministic, handles BBC and most news sites |
| Persistent storage | AWS S3 | Pennies/month; user already has AWS credentials |
| Auth | Single shared password via `st.secrets` | Community Cloud apps are public; this prevents random visitors from running up the AI bill |
| Source / CI | GitHub repo → Streamlit Cloud auto-deploy on push to `main` | No CI setup required |

## Architecture

```
                ┌────────────────────────────┐
                │  Streamlit app (app.py)    │
                │   - password gate          │
                │   - URL input              │
                │   - audio player           │
                │   - past-episodes list     │
                └────┬──────────────┬────────┘
                     │              │
            ┌────────▼─────┐  ┌─────▼────────────────┐
            │ extractor.py │  │ storage.py (boto3)   │
            │  trafilatura │  │  S3: audio + index   │
            └────────┬─────┘  └─────▲────────────────┘
                     │              │
            ┌────────▼─────┐  ┌─────┴────────────────┐
            │  dialog.py   │  │       tts.py         │
            │  Gemini Flash│─▶│ Gemini Flash TTS     │
            │  (text)      │  │ (multi-speaker audio)│
            └──────────────┘  └──────────────────────┘
```

## Components

Each module is a single small file with a narrow public surface and clear inputs/outputs. They depend only on each other through these surfaces — no shared mutable state.

### `app.py` — Streamlit UI
- Password gate at top using `st.secrets["app_password"]`. Wrong/missing password renders nothing else.
- URL text input + "Generate" button.
- Progress indicator while generating (extract → script → audio → upload).
- Audio player for the current/just-generated episode using `st.audio` pointed at a presigned S3 URL.
- "Past Episodes" section below: list of saved episodes (title, source, date) each with a play button that loads its audio.

### `extractor.py` — Article extraction
```python
class Article(TypedDict):
    url: str
    title: str
    body: str        # plain text, paragraphs separated by \n\n
    source: str      # e.g. "bbc.com"

def extract_article(url: str) -> Article: ...
class ExtractionError(Exception): ...
```
- Fetches HTML with `requests` (5s timeout, browser-like User-Agent).
- Runs `trafilatura.extract` with `include_comments=False`.
- Raises `ExtractionError` if no body could be extracted or body is shorter than 200 characters.

### `dialog.py` — Dialog script generation
```python
class Turn(TypedDict):
    speaker: Literal["host_a", "host_b"]
    text: str

def generate_dialog(article: Article) -> list[Turn]: ...
class DialogError(Exception): ...
```
- One Gemini 2.5 Flash text call with a system prompt that instructs:
  - Two hosts named "Alex" (host_a) and "Sam" (host_b) — conversational, curious.
  - Stay faithful to the article. Don't invent facts.
  - Length proportional to article: aim for ~1 minute of audio per 300 words of source.
  - Output strict JSON: `[{"speaker": "host_a"|"host_b", "text": "..."}]`.
- Parses JSON; on parse failure raises `DialogError`.

### `tts.py` — Multi-speaker audio
```python
def render_audio(turns: list[Turn]) -> bytes: ...   # WAV bytes
class TtsError(Exception): ...
```
- One Gemini 2.5 Flash TTS call with `multiSpeakerVoiceConfig`:
  - `host_a` → one preset voice (e.g. "Charon")
  - `host_b` → a contrasting preset voice (e.g. "Kore")
- Input is a single string with turns concatenated as `"Alex: ...\nSam: ...\n..."` so the model knows speaker boundaries.
- Returns raw PCM/WAV bytes from the API response.

### `storage.py` — S3 persistence
```python
class Episode(TypedDict):
    id: str          # uuid4
    url: str
    title: str
    source: str
    created_at: str  # ISO 8601
    audio_key: str   # S3 key

def save_episode(article: Article, audio: bytes) -> Episode: ...
def list_episodes() -> list[Episode]: ...        # newest first
def get_audio_url(episode: Episode) -> str: ...  # 1-hour presigned GET URL
```
- Bucket name comes from `st.secrets["s3_bucket"]`. AWS credentials from `st.secrets`.
- Audio stored at `audio/{episode_id}.wav`.
- Episode index stored as a single JSON object at `index/episodes.json`. `save_episode` reads-modifies-writes it. (Single-user app — no concurrent-write concerns.)

### Secrets (`.streamlit/secrets.toml`, gitignored)
```toml
app_password = "..."
gemini_api_key = "..."
aws_access_key_id = "..."
aws_secret_access_key = "..."
aws_region = "us-west-2"
s3_bucket = "rjain-newpodcaster"
```

## Data flow (happy path)

1. User enters password → app unlocks.
2. User pastes URL, clicks "Generate".
3. `extractor.extract_article(url)` → `Article`.
4. `dialog.generate_dialog(article)` → `list[Turn]`.
5. `tts.render_audio(turns)` → `bytes`.
6. `storage.save_episode(article, audio)` → `Episode` (writes audio to S3, appends to index).
7. UI plays the new episode and refreshes the "Past Episodes" list.

## Error handling

- Each step that calls an external service catches its own exceptions and raises one of `ExtractionError`, `DialogError`, `TtsError`, or a `StorageError`.
- `app.py` shows a user-facing message per error type (e.g. "Couldn't read that article — try a different URL") and logs the underlying exception.
- An episode is **only** saved if all steps succeed. No half-finished episodes in the library.
- No automatic retries. The user clicks "Generate" again if they want to try again.

## Testing

| Module | Approach |
|---|---|
| `extractor` | Unit tests against saved HTML fixtures (BBC, Reuters, NYT free article). Tests assert title and body are extracted, and that an empty page raises `ExtractionError`. |
| `dialog` | Unit tests with a mocked Gemini client. Test JSON parsing, malformed-response handling, and that the prompt includes article title + body. |
| `tts` | Unit tests with a mocked Gemini client. Test that the request includes both speaker configs and that turns are formatted correctly. |
| `storage` | Unit tests using `moto` to mock S3. Test save/list/presigned-URL flow and the read-modify-write of the index. |
| End-to-end | One pytest gated by `RUN_E2E=1` that hits a real BBC URL end-to-end. Not in CI by default — used for manual verification before deploys. |
| UI (`app.py`) | Not unit-tested. Manual verification: paste a BBC URL on the deployed site, confirm audio plays and episode appears in the list. |

## Deployment

1. Push to `main` on GitHub.
2. Streamlit Community Cloud detects the push and redeploys automatically.
3. Secrets are managed in the Streamlit Cloud dashboard (not in the repo).

## Cost estimate

| Item | Estimate |
|---|---|
| Streamlit Community Cloud | $0 |
| Gemini Flash text (script) | ~$0 (under free tier for personal use) |
| Gemini Flash TTS (audio) | $0 if under free tier; up to ~$5/month otherwise |
| S3 storage (~100 episodes ≈ 500 MB) | ~$0.01/month |
| S3 GET / transfer (personal listening) | ~$0.05–0.20/month |
| **Total** | **~$0–$5/month** |

## Risks / open items

- **Gemini 2.5 Flash TTS free-tier limits**: exact quotas should be confirmed against current Google docs before deploy. If multi-speaker TTS isn't free-tier eligible at the time of build, fall back to two separate single-voice TTS calls (one per speaker) and stitch the WAVs together with `pydub` — same audible result, modestly more code.
- **Article extraction failures**: some sites (paywalled, JS-only) won't work with `trafilatura`. Acceptable in v1 — user picks a different URL. Add Jina Reader (`https://r.jina.ai/<url>`) fallback in a v2 if it becomes a real problem.
- **Public Streamlit Cloud URL**: even with a password gate, the URL is discoverable. The password gate is sufficient since the only blast radius is a small Gemini bill. Don't store anything sensitive in S3.
