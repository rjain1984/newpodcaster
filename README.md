# newpodcaster

A daily AI podcast of BBC Sport football news. Personal project — single user.

Each morning at 09:00 PT, an AWS Lambda discovers new BBC Sport football articles (European + World Cup; falls back to Premier League + Arsenal when news is heavy), turns each into a two-host NotebookLM-style podcast, and stores the audio on S3. A Streamlit web app on Community Cloud lets me listen on my phone. Capped at 5 episodes per day to stay inside free-tier AI quotas.

## Stack

- **Viewer**: Streamlit on Streamlit Community Cloud
- **Generator**: AWS Lambda on a daily EventBridge cron
- **AI**: Google Gemini 2.5 Flash (dialog) + Gemini 2.5 Flash TTS (multi-speaker)
- **Storage**: AWS S3
- **Article parsing**: `trafilatura`; **RSS**: `feedparser`
- **Lambda deploy**: AWS SAM via GitHub Actions

## Status

Design approved 2026-05-28 (v2 — spec rewritten from the original paste-URL design). See [`docs/superpowers/specs/2026-05-28-newpodcaster-design.md`](docs/superpowers/specs/2026-05-28-newpodcaster-design.md). Implementation plan pending.
