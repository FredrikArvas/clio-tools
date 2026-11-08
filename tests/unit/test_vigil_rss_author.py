"""extract_author() i clio-vigil/collectors/rss_collector.py."""
import sys
from pathlib import Path

import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clio-vigil"))

from collectors.rss_collector import extract_author  # noqa: E402


def _entry(**kwargs):
    return feedparser.FeedParserDict(kwargs)


def test_author_detail_med_namn():
    entry = _entry(author_detail=feedparser.FeedParserDict(name="  Anna Svensson "))
    assert extract_author(entry) == "Anna Svensson"


def test_author_detail_med_namn_none_kraschar_inte():
    # DN/Aftonbladet/SvD: author_detail finns men name är None
    entry = _entry(author_detail=feedparser.FeedParserDict(name=None, email="x@y.se"))
    assert extract_author(entry) is None


def test_faller_tillbaka_pa_author():
    entry = _entry(author_detail=feedparser.FeedParserDict(name=None), author="Per Persson")
    assert extract_author(entry) == "Per Persson"


def test_ingen_byline():
    assert extract_author(_entry()) is None


def test_tom_strang_blir_none():
    assert extract_author(_entry(author="   ")) is None
