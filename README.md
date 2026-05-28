# newpodcaster

Paste a news article URL, get a two-host AI podcast about it. Personal project — single user.

## Stack

- Streamlit on Streamlit Community Cloud (frontend + app server)
- Google Gemini 2.5 Flash (dialog script) + Gemini 2.5 Flash TTS (multi-speaker audio)
- AWS S3 (audio + episode index)
- `trafilatura` for article extraction

## Status

Design approved 2026-05-28. See [`docs/superpowers/specs/2026-05-28-newpodcaster-design.md`](docs/superpowers/specs/2026-05-28-newpodcaster-design.md). Implementation plan pending.
