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
    """Render all episodes for one tab as a single HTML block using native
    HTML5 <audio> elements. No wavesurfer.js. The browser handles streaming,
    decoding, scrubbing — much more reliable than embedding a JS audio library
    inside an iframe under Streamlit Cloud's resource ceiling.

    What we keep: clickable thumbnails, custom speed buttons (1x/1.25x/1.5x),
    auto-play-next on episode end, pause-others-when-one-plays."""
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
        # preload="none" keeps idle cards lightweight; native audio fetches
        # on first interaction.
        cards.append(f"""
<div class="ep-card" id="ep-{i}">
  {thumb}
  <h3>{title}</h3>
  <p class="meta">{date_str}</p>
  <audio class="audio" id="audio-{i}" preload="none" controls
         src="{html.escape(audio_urls[i])}"></audio>
  <div class="speed-group" role="group" aria-label="Playback speed">
    <button class="speed-btn active" data-idx="{i}" data-rate="1">1×</button>
    <button class="speed-btn" data-idx="{i}" data-rate="1.25">1.25×</button>
    <button class="speed-btn" data-idx="{i}" data-rate="1.5">1.5×</button>
  </div>
</div>
""")
    cards_html = "\n".join(cards)
    return f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  :root {{ color-scheme: dark light; }}
  html, body {{
    margin: 0; padding: 0;
    background: transparent;
    color: #FAFAFA;
    font-family: 'Noto Sans Devanagari', -apple-system, BlinkMacSystemFont,
                 'Segoe UI', sans-serif;
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
    margin: 0 0 10px;
    font-size: 0.85rem;
    color: rgba(250,250,250,0.65);
  }}
  .ep-card .audio {{
    width: 100%;
    margin: 8px 0;
    height: 36px;
    /* Subtle dark-theme adjustment for native player chrome */
    filter: invert(0.85) hue-rotate(180deg) brightness(0.9);
  }}
  .ep-card .speed-group {{
    display: flex; gap: 4px; margin-top: 6px;
  }}
  .ep-card .speed-btn {{
    background: transparent;
    color: rgba(250,250,250,0.75);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 0.78rem;
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
</style>
<div class="tab-content">
  {cards_html}
</div>
<script>
  (function() {{
    const audios = Array.from(document.querySelectorAll('audio.audio'));

    audios.forEach((audio, idx) => {{
      const card = document.getElementById('ep-' + idx);

      // Pause all other audios when this one plays.
      audio.addEventListener('play', () => {{
        audios.forEach((a, i) => {{ if (i !== idx) a.pause(); }});
        if (card) card.classList.add('playing');
      }});
      audio.addEventListener('pause', () => {{
        if (card) card.classList.remove('playing');
      }});

      // Auto-play next episode when this one finishes.
      audio.addEventListener('ended', () => {{
        if (card) card.classList.remove('playing');
        const next = audios[idx + 1];
        if (next) {{
          // Small delay so the transition is perceptible.
          setTimeout(() => next.play().catch(() => {{ /* user-gesture limit */ }}), 600);
          const nextCard = document.getElementById('ep-' + (idx + 1));
          if (nextCard) nextCard.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}
      }});

      // Per-card speed buttons; HTMLAudioElement.preservesPitch defaults true.
      document.querySelectorAll('#ep-' + idx + ' .speed-btn').forEach((sb) => {{
        sb.addEventListener('click', () => {{
          const rate = parseFloat(sb.getAttribute('data-rate'));
          audio.playbackRate = rate;
          document.querySelectorAll('#ep-' + idx + ' .speed-btn')
            .forEach((b) => b.classList.remove('active'));
          sb.classList.add('active');
        }});
      }});
    }});
  }})();
</script>
"""


def _inject_parent_styles() -> None:
    """Inject CSS into the Streamlit parent page to enlarge tab fonts +
    load Noto Sans Devanagari for Hindi text rendering."""
    st.markdown(
        """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
          /* Devanagari font for content text only. Targeting spans/divs killed
             Material Symbols icons (they rely on their own font-family).
             Note: NOT using !important — Streamlit's icon spans need to keep
             their Material Symbols font. */
          html, body, h1, h2, h3, h4, h5, h6, p {
            font-family: 'Noto Sans Devanagari', "Source Sans Pro",
                         -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          }
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
