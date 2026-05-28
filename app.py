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
