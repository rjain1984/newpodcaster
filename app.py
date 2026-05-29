"""Streamlit viewer for newpodcaster. Reads episodes from S3, plays them with a waveform."""
from __future__ import annotations

import html
import json
from datetime import datetime

import boto3
import streamlit as st
import streamlit.components.v1 as components
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


def _human_date(iso: str) -> str:
    """Format ISO 8601 UTC timestamp as a short readable date with explicit UTC label."""
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%b %d, %Y at %I:%M %p UTC")


def _player_html(ep_id: str, audio_url: str) -> str:
    """Render a wavesurfer.js waveform player for one episode."""
    safe = ep_id.replace("-", "")
    audio_url_js = json.dumps(audio_url)
    return f"""
<style>
  body {{ margin: 0; background: transparent; color: inherit; }}
  .player-{safe} {{
    background: rgba(255, 255, 255, 0.04);
    border-radius: 8px;
    padding: 12px 14px;
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
  }}
  .wave-{safe} {{ width: 100%; margin-bottom: 10px; }}
  .ctrl-{safe} {{ display: flex; align-items: center; gap: 12px; }}
  .play-{safe} {{
    background: #FF4B4B;
    color: white;
    border: none;
    border-radius: 50%;
    width: 40px;
    height: 40px;
    font-size: 16px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }}
  .play-{safe}:hover {{ background: #e63f3f; }}
  .time-{safe} {{ font-family: monospace; font-size: 0.9em; opacity: 0.75; }}
</style>
<div class="player-{safe}">
  <div class="wave-{safe}" id="wave-{safe}"></div>
  <div class="ctrl-{safe}">
    <button class="play-{safe}" id="play-{safe}" aria-label="Play">▶</button>
    <span class="time-{safe}" id="time-{safe}">--:-- / --:--</span>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/wavesurfer.js@7.8.6/dist/wavesurfer.min.js"></script>
<script>
(function() {{
  function fmt(s) {{
    s = Math.floor(s || 0);
    var m = Math.floor(s / 60);
    var sec = s % 60;
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }}
  var ws = WaveSurfer.create({{
    container: '#wave-{safe}',
    waveColor: 'rgba(255, 75, 75, 0.35)',
    progressColor: '#FF4B4B',
    cursorColor: '#FF4B4B',
    height: 64,
    barWidth: 2,
    barGap: 1,
    barRadius: 1,
    url: {audio_url_js},
  }});
  var btn = document.getElementById('play-{safe}');
  var timeEl = document.getElementById('time-{safe}');
  btn.addEventListener('click', function() {{ ws.playPause(); }});
  ws.on('ready', function() {{
    timeEl.textContent = '0:00 / ' + fmt(ws.getDuration());
  }});
  ws.on('play',  function() {{ btn.textContent = '⏸'; }});
  ws.on('pause', function() {{ btn.textContent = '▶'; }});
  ws.on('finish', function() {{ btn.textContent = '▶'; ws.setTime(0); }});
  ws.on('timeupdate', function(t) {{
    timeEl.textContent = fmt(t) + ' / ' + fmt(ws.getDuration());
  }});
}})();
</script>
"""


def main():
    st.set_page_config(page_title="Newpodcaster", page_icon="🎙️", layout="centered")
    st.title("🎙️ Newpodcaster")

    episodes = _load_episodes()
    if not episodes:
        st.info("No episodes yet. Check back after 09:00 PT.")
        return

    st.caption(f"{len(episodes)} episodes — newest first")
    for ep in episodes:
        with st.container(border=True):
            image_url = ep.get("image_url")
            if image_url:
                # Clickable thumbnail that opens the original article in a new tab.
                st.markdown(
                    f'<a href="{html.escape(ep["url"])}" target="_blank" rel="noopener">'
                    f'<img src="{html.escape(image_url)}" '
                    f'style="width:100%;max-height:300px;object-fit:cover;'
                    f'border-radius:6px;display:block;cursor:pointer;" /></a>',
                    unsafe_allow_html=True,
                )
            st.subheader(ep["title"])
            st.caption(_human_date(ep["created_at"]))
            components.html(
                _player_html(ep["id"], _presigned_url(ep["audio_key"])),
                height=160,
            )


if __name__ == "__main__":
    main()
