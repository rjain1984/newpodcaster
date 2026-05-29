"""Streamlit viewer for newpodcaster. Three topic tabs + auto-play queue."""
from __future__ import annotations

import html
import json
from datetime import datetime

import boto3
import streamlit as st
import streamlit.components.v1 as components
from botocore.exceptions import ClientError

EPISODES_KEY = "index/episodes.json"
# 6h instead of 1h so an open browser tab doesn't drift into expired-URL territory.
PRESIGNED_URL_TTL_SECONDS = 6 * 3600
TABS = [
    ("football", ":material/sports_soccer: Football"),
    ("f1", ":material/sports_motorsports: F1"),
    ("india", ":material/temple_hindu: India"),
    ("hindi", ":material/translate: हिंदी"),
]


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


def _human_date(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%b %d, %Y at %I:%M %p UTC")


def _infer_topic(ep: dict) -> str:
    if ep.get("topic"):
        return ep["topic"]
    url = ep.get("url", "")
    if "formula1" in url:
        return "f1"
    if "/hindi/" in url or url.startswith("https://www.bbc.com/hindi"):
        return "hindi"
    if "/asia/india/" in url or url.startswith("https://www.bbc.com/news/world/asia/india"):
        return "india"
    return "football"


def _tab_html(episodes: list[dict], audio_urls: list[str]) -> str:
    """Render all episodes for one tab as a single HTML block with coordinated
    wavesurfer.js players that auto-advance to the next episode when one finishes."""
    cards = []
    for i, ep in enumerate(episodes):
        title = html.escape(ep["title"])
        article_url = html.escape(ep["url"])
        date_str = html.escape(_human_date(ep["created_at"]))
        image_url = ep.get("image_url")
        thumb = ""
        if image_url:
            thumb = (
                f'<a href="{article_url}" target="_blank" rel="noopener">'
                f'<img class="thumb" src="{html.escape(image_url)}" '
                f'alt="article thumbnail"/></a>'
            )
        cards.append(f"""
<div class="ep-card" id="ep-{i}">
  {thumb}
  <h3>{title}</h3>
  <p class="meta">{date_str}</p>
  <div class="wave" id="wave-{i}"></div>
  <div class="ctrl">
    <button class="play-btn" id="play-{i}" data-idx="{i}" aria-label="Play">▶</button>
    <span class="time" id="time-{i}">--:-- / --:--</span>
    <div class="speed-group" role="group" aria-label="Playback speed">
      <button class="speed-btn active" data-idx="{i}" data-rate="1">1×</button>
      <button class="speed-btn" data-idx="{i}" data-rate="1.25">1.25×</button>
      <button class="speed-btn" data-idx="{i}" data-rate="1.5">1.5×</button>
    </div>
  </div>
</div>
""")
    audio_urls_js = json.dumps(audio_urls)
    cards_html = "\n".join(cards)
    return f"""
<style>
  :root {{ color-scheme: dark light; }}
  html, body {{
    margin: 0; padding: 0;
    background: transparent;
    color: #FAFAFA;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }}
  .ep-card {{
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    padding: 14px;
    margin-bottom: 18px;
    background: rgba(255,255,255,0.03);
  }}
  .ep-card .thumb {{
    width: 100%;
    height: auto;
    border-radius: 6px;
    display: block;
    cursor: pointer;
    transition: transform 0.2s ease;
    background: rgba(0,0,0,0.2);
  }}
  .ep-card .thumb:hover {{ transform: scale(1.005); }}
  .ep-card h3 {{
    margin: 14px 0 6px;
    font-size: 1.1rem;
    font-weight: 600;
    color: #FAFAFA;
    line-height: 1.35;
  }}
  .ep-card .meta {{
    margin: 0 0 12px;
    font-size: 0.85rem;
    color: rgba(250,250,250,0.65);
  }}
  .ep-card .wave {{
    width: 100%;
    margin: 10px 0;
    min-height: 64px;
  }}
  .ep-card .ctrl {{
    display: flex; align-items: center; gap: 14px;
  }}
  .ep-card .play-btn {{
    background: #FF4B4B; color: white;
    border: none; border-radius: 50%;
    width: 44px; height: 44px;
    font-size: 18px; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }}
  .ep-card .play-btn:hover {{ background: #e63f3f; }}
  .ep-card .time {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.9rem;
    color: rgba(250,250,250,0.75);
  }}
  .ep-card .speed-group {{
    display: flex; gap: 4px; margin-left: auto;
  }}
  .ep-card .speed-btn {{
    background: transparent;
    color: rgba(250,250,250,0.75);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 0.75rem;
    cursor: pointer;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .ep-card .speed-btn:hover {{ background: rgba(255,255,255,0.08); }}
  .ep-card .speed-btn.active {{
    background: rgba(255,75,75,0.18);
    color: #FF4B4B;
    border-color: rgba(255,75,75,0.55);
  }}
  .ep-card.playing {{ border-color: rgba(255,75,75,0.55); }}
  .err {{ color: #ff8a8a; font-size: 0.85em; }}
</style>
<div class="tab-content">
  {cards_html}
</div>
<script type="module">
  // wavesurfer.js v7 ships ESM only (no UMD bundle).
  import WaveSurfer from 'https://cdn.jsdelivr.net/npm/wavesurfer.js@7.8.6/dist/wavesurfer.esm.js';

  const AUDIO_URLS = {audio_urls_js};
  const players = [];

  function fmt(s) {{
    s = Math.floor(s || 0);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }}

  function pauseAllExcept(idx) {{
    players.forEach((p, i) => {{ if (i !== idx && p) p.pause(); }});
  }}

  function playEpisode(idx) {{
    if (idx < 0 || idx >= players.length || !players[idx]) return;
    pauseAllExcept(idx);
    players[idx].play();
    const card = document.getElementById('ep-' + idx);
    if (card) card.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
  }}

  AUDIO_URLS.forEach((url, idx) => {{
    const ws = WaveSurfer.create({{
      container: '#wave-' + idx,
      waveColor: 'rgba(255,75,75,0.40)',
      progressColor: '#FF4B4B',
      cursorColor: '#FF4B4B',
      height: 64,
      barWidth: 2,
      barGap: 1,
      barRadius: 1,
      url: url,
    }});
    const btn = document.getElementById('play-' + idx);
    const timeEl = document.getElementById('time-' + idx);
    const card = document.getElementById('ep-' + idx);

    btn.addEventListener('click', () => {{
      if (ws.isPlaying()) {{
        ws.pause();
      }} else {{
        playEpisode(idx);
      }}
    }});

    // Wire up the speed buttons for THIS card. Default rate is 1x (natural).
    // Second arg `true` = preserve pitch (no chipmunk effect).
    document.querySelectorAll('.ep-card#ep-' + idx + ' .speed-btn').forEach((sb) => {{
      sb.addEventListener('click', () => {{
        const rate = parseFloat(sb.getAttribute('data-rate'));
        ws.setPlaybackRate(rate, true);
        document.querySelectorAll('.ep-card#ep-' + idx + ' .speed-btn')
          .forEach((b) => b.classList.remove('active'));
        sb.classList.add('active');
      }});
    }});

    // Show loading state until ws is ready (replaces the static --:-- / --:--)
    timeEl.textContent = 'loading…';

    // Safety net: if the audio hasn't loaded after 15s, treat as failed and
    // expose a retry button. This catches silent decode failures + dropped requests.
    const readyTimeout = setTimeout(() => {{
      if (!ws._npReady) {{
        timeEl.innerHTML = '<span class="err">audio slow / failed</span> '
          + '<button class="speed-btn" id="retry-' + idx + '">↻ reload</button>';
        const retryBtn = document.getElementById('retry-' + idx);
        if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
      }}
    }}, 15000);

    ws.on('ready', () => {{
      ws._npReady = true;
      clearTimeout(readyTimeout);
      timeEl.textContent = '0:00 / ' + fmt(ws.getDuration());
    }});
    ws.on('play',  () => {{
      btn.textContent = '⏸';
      card.classList.add('playing');
    }});
    ws.on('pause', () => {{
      btn.textContent = '▶';
      card.classList.remove('playing');
    }});
    ws.on('finish', () => {{
      btn.textContent = '▶';
      ws.setTime(0);
      card.classList.remove('playing');
      if (idx + 1 < players.length) {{
        setTimeout(() => playEpisode(idx + 1), 600);
      }}
    }});
    ws.on('timeupdate', (t) => {{
      timeEl.textContent = fmt(t) + ' / ' + fmt(ws.getDuration());
    }});
    ws.on('error', (e) => {{
      clearTimeout(readyTimeout);
      timeEl.innerHTML = '<span class="err">audio load failed</span> '
        + '<button class="speed-btn" id="retry-' + idx + '">↻ reload</button>';
      const retryBtn = document.getElementById('retry-' + idx);
      if (retryBtn) retryBtn.addEventListener('click', () => location.reload());
      console.error('wavesurfer error for', url, e);
    }});

    players.push(ws);
  }});
</script>
"""


def _inject_parent_styles() -> None:
    """Inject CSS into the Streamlit parent page to enlarge tab fonts."""
    st.markdown(
        """
        <style>
          .stTabs [data-baseweb="tab-list"] { gap: 8px; }
          .stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"] {
            font-size: 1.15rem;
            padding: 12px 24px;
            height: auto;
          }
          .stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"] p {
            font-size: 1.15rem;
          }
          /* Enlarge Material Symbols icons inside tab labels */
          .stTabs button[data-baseweb="tab"] span[data-testid="stIconMaterial"] {
            font-size: 1.6rem !important;
            margin-right: 4px;
          }
          .stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"][aria-selected="true"] {
            font-weight: 600;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title="Newpodcaster", page_icon="🎙️", layout="centered")
    _inject_parent_styles()
    st.title("🎙️ Newpodcaster")

    episodes = _load_episodes()
    if not episodes:
        st.info("No episodes yet. Check back after 09:00 PT.")
        return

    grouped: dict[str, list[dict]] = {key: [] for key, _ in TABS}
    for ep in episodes:
        topic = _infer_topic(ep)
        if topic in grouped:
            grouped[topic].append(ep)

    tabs = st.tabs([label for _, label in TABS])
    for (topic_key, _label), tab in zip(TABS, tabs, strict=True):
        with tab:
            tab_episodes = grouped[topic_key]
            if not tab_episodes:
                st.info(f"No {topic_key} episodes yet.")
                continue
            st.caption(
                f"{len(tab_episodes)} episode{'s' if len(tab_episodes) != 1 else ''} "
                f"— newest first · auto-plays next on finish"
            )
            audio_urls = [_presigned_url(ep["audio_key"]) for ep in tab_episodes]
            # ~720px per card (taller thumbnails uncropped). Generous so nothing clips.
            iframe_height = max(800, 720 * len(tab_episodes) + 60)
            components.html(
                _tab_html(tab_episodes, audio_urls),
                height=iframe_height,
                scrolling=True,
            )


if __name__ == "__main__":
    main()
