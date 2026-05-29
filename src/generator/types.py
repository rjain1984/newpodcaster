"""Shared data types used across the generator pipeline."""
from typing import Literal, NotRequired, TypedDict


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
    image_url: NotRequired[str | None]  # primary image URL from article metadata, if any


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
    image_url: NotRequired[str | None]  # carried through from Article
    topic: NotRequired[str]  # "football" | "f1" | "india"
