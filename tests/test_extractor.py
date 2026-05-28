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
