"""
test_fulltext_ft1.py — Enhetstester för FT1-stegen i fulltext_fetcher.py.

Semantic Scholar, Wayback och 403-spårning. Inga nätverksanrop:
alla HTTP-svar simuleras med FakeHttp.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import fulltext_fetcher as ff  # noqa: E402


# ── Hjälpklasser ──────────────────────────────────────────────────────────────

@dataclass
class FakeResponse:
    status: int
    body: bytes = b""
    content_type: str = ""
    final_url: str = ""

    def __post_init__(self):
        if not self.final_url:
            self.final_url = ""


class FakeHttp:
    """Fake HTTP-klient. Nycklar är 'netloc' eller 'netloc/path-prefix'.

    Matchning: exakt netloc-träff slår alltid substring-träff, för att undvika
    att Wayback-URL:er (som innehåller den ursprungliga host:en) triggar fel svar.
    """

    def __init__(self, responses: dict):
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, *, params=None, headers=None, timeout=None, deadline=None):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        netloc = parsed.netloc or ""
        self.calls.append((url, params or {}))
        # Prioritet 1: netloc-träff (exakt eller subdomain) med valfri path-prefix
        for key, response in self._responses.items():
            key_host = key.split("/")[0]
            key_path = key[len(key_host):]
            host_match = (netloc == key_host or netloc.endswith("." + key_host))
            if host_match and (not key_path or parsed.path.startswith(key_path)):
                r = response
                return ff.HttpResult(r.status, r.body, r.content_type, r.final_url or url)
        # Prioritet 2: substring-match (bakåtkompatibilitet, används av API-URL:er med path)
        for key, response in self._responses.items():
            if key in url and "/" in key:
                r = response
                return ff.HttpResult(r.status, r.body, r.content_type, r.final_url or url)
        return ff.HttpResult(404, b"", "", url)


def _pdf_bytes() -> bytes:
    """Minimal giltig PDF-signatur + 600 ord lorem ipsum."""
    words = ("lorem ipsum dolor sit amet consectetur adipiscing elit " * 100).split()[:600]
    text = " ".join(words)
    return b"%PDF-1.4\n" + text.encode("utf-8")


def _json_bytes(data: dict) -> bytes:
    return json.dumps(data).encode("utf-8")


def _fetcher(http, level="delbar", tmp_path=None):
    if tmp_path is None:
        import tempfile
        tmp_path = Path(tempfile.mkdtemp())
    t0 = time.monotonic()
    return ff.FulltextFetcher(tmp_path, level=level, http=http,
                              clock=time.monotonic, sleep=lambda s: None), t0


# ── Nivåstyrning ──────────────────────────────────────────────────────────────

def test_delbar_includes_semantic_scholar_and_wayback():
    steps = ff.STEPS_BY_LEVEL["delbar"]
    assert "semantic_scholar" in steps
    assert "wayback" in steps


def test_standard_excludes_ft1_steps():
    steps = ff.STEPS_BY_LEVEL["standard"]
    assert "semantic_scholar" not in steps
    assert "wayback" not in steps


def test_snabb_only_openalex():
    assert ff.STEPS_BY_LEVEL["snabb"] == ("openalex",)


# ── Semantic Scholar: DOI-uppslag ─────────────────────────────────────────────

def test_semantic_scholar_returns_pdf_url(tmp_path):
    ss_resp = _json_bytes({"paperId": "abc", "openAccessPdf": {"url": "https://arxiv.org/pdf/1234.pdf"}})
    pdf = _pdf_bytes()
    http = FakeHttp({
        "semanticscholar.org": FakeResponse(200, ss_resp, "application/json"),
        "arxiv.org/pdf/1234": FakeResponse(200, pdf, "application/pdf"),
    })
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    source = {"n": 1, "doi": "10.1234/test", "title": "T", "abstract": None,
              "url": None, "source_id": "x:1"}
    ctx = ff._Context(deadline=time.monotonic() + 60)
    cands = fetcher._step_semantic_scholar(source, ctx)
    assert len(cands) == 1
    assert cands[0].route == "semantic_scholar"
    assert "arxiv.org" in cands[0].url


def test_semantic_scholar_no_doi_skips(tmp_path):
    http = FakeHttp({})
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    source = {"n": 1, "doi": None, "title": "T", "abstract": None, "url": None, "source_id": "x:1"}
    ctx = ff._Context(deadline=time.monotonic() + 60)
    cands = fetcher._step_semantic_scholar(source, ctx)
    assert cands == []
    assert any("DOI" in s or "doi" in s.lower() for s in ctx.skips)


def test_semantic_scholar_no_oa_pdf_skips(tmp_path):
    ss_resp = _json_bytes({"paperId": "abc", "openAccessPdf": None})
    http = FakeHttp({"semanticscholar.org": FakeResponse(200, ss_resp, "application/json")})
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    source = {"n": 1, "doi": "10.9999/closed", "title": "T", "abstract": None,
              "url": None, "source_id": "x:1"}
    ctx = ff._Context(deadline=time.monotonic() + 60)
    cands = fetcher._step_semantic_scholar(source, ctx)
    assert cands == []
    assert any("semantic_scholar" in s for s in ctx.skips)


def test_semantic_scholar_api_error_returns_empty(tmp_path):
    http = FakeHttp({"semanticscholar.org": FakeResponse(429, b"rate limited")})
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    source = {"n": 1, "doi": "10.9999/x", "title": "T", "abstract": None, "url": None, "source_id": "x:1"}
    ctx = ff._Context(deadline=time.monotonic() + 60)
    cands = fetcher._step_semantic_scholar(source, ctx)
    assert cands == []
    assert any("semantic_scholar" in f for f in ctx.failures)


# ── Wayback Machine ───────────────────────────────────────────────────────────

def _wayback_resp(archived_url: str, available: bool = True) -> bytes:
    return _json_bytes({
        "url": "https://example.com/paper",
        "archived_snapshots": {
            "closest": {
                "available": available,
                "url": archived_url,
                "timestamp": "20201115120000",
                "status": "200",
            }
        }
    })


def test_wayback_fetches_archived_url(tmp_path):
    archived = "https://web.archive.org/web/20201115/https://example.com/paper"
    pdf = _pdf_bytes()
    http = FakeHttp({
        "archive.org/wayback": FakeResponse(200, _wayback_resp(archived), "application/json"),
        "web.archive.org": FakeResponse(200, pdf, "application/pdf"),
    })
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    ctx = ff._Context(deadline=time.monotonic() + 60)
    ctx.got_403_urls.append("https://example.com/paper")
    cands = fetcher._step_wayback({"n": 1}, ctx)
    assert len(cands) == 1
    assert cands[0].route == "wayback"
    assert "web.archive.org" in cands[0].url


def test_wayback_skips_when_no_403s(tmp_path):
    http = FakeHttp({})
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    ctx = ff._Context(deadline=time.monotonic() + 60)
    cands = fetcher._step_wayback({"n": 1}, ctx)
    assert cands == []
    assert any("wayback" in s for s in ctx.skips)


def test_wayback_not_available_returns_empty(tmp_path):
    archived = ""
    resp = _json_bytes({
        "url": "https://example.com/paper",
        "archived_snapshots": {"closest": {"available": False, "url": "", "timestamp": ""}}
    })
    http = FakeHttp({"archive.org/wayback": FakeResponse(200, resp, "application/json")})
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    ctx = ff._Context(deadline=time.monotonic() + 60)
    ctx.got_403_urls.append("https://example.com/paper")
    cands = fetcher._step_wayback({"n": 1}, ctx)
    assert cands == []
    assert any("wayback" in s for s in ctx.skips)


def test_wayback_empty_snapshots_returns_empty(tmp_path):
    resp = _json_bytes({"url": "x", "archived_snapshots": {}})
    http = FakeHttp({"archive.org/wayback": FakeResponse(200, resp, "application/json")})
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    ctx = ff._Context(deadline=time.monotonic() + 60)
    ctx.got_403_urls.append("https://example.com/paper")
    cands = fetcher._step_wayback({"n": 1}, ctx)
    assert cands == []


# ── 403-spårning ──────────────────────────────────────────────────────────────

def test_403_from_content_url_added_to_got_403(tmp_path):
    """403 från ett innehållsanrop spåras i ctx.got_403_urls."""
    final = "https://publisher.com/article"
    http = FakeHttp({
        "publisher.com": FakeResponse(403, b"", "", final),
    })
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    ctx = ff._Context(deadline=time.monotonic() + 60)
    fetcher._get("direct_url", "https://publisher.com/article", ctx, track_403=True)
    assert final in ctx.got_403_urls


def test_403_not_tracked_when_track_403_false(tmp_path):
    """API-anrop med track_403=False lagrar inte 403 i ctx."""
    http = FakeHttp({"api.example.com": FakeResponse(403, b"")})
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    ctx = ff._Context(deadline=time.monotonic() + 60)
    fetcher._get("openalex", "https://api.example.com/works/W1", ctx, track_403=False)
    assert ctx.got_403_urls == []


def test_200_not_added_to_got_403(tmp_path):
    """Lyckade anrop spåras inte."""
    http = FakeHttp({"ok.com": FakeResponse(200, _pdf_bytes(), "application/pdf")})
    fetcher, _ = _fetcher(http, tmp_path=tmp_path)
    ctx = ff._Context(deadline=time.monotonic() + 60)
    fetcher._get("direct_url", "https://ok.com/paper.pdf", ctx, track_403=True)
    assert ctx.got_403_urls == []


# ── Hel kedja på delbar-nivå ──────────────────────────────────────────────────

def _html_bytes(n_words: int = 600) -> bytes:
    """Enkel HTML-sida med n_words ord; trafilatura kan extrahera den."""
    para = " ".join(["lorem ipsum dolor sit amet"] * (n_words // 5 + 1))
    return (
        f"<html><body><article><h1>Title</h1><p>{para}</p></article></body></html>"
    ).encode("utf-8")


def test_delbar_uses_wayback_after_direct_403(tmp_path):
    """På delbar-nivå: direkthämtning ger 403, Wayback hittar ett arkivexemplar."""
    archived = "https://web.archive.org/web/20201115/https://publisher.com/article"

    http = FakeHttp({
        # OpenAlex: closed
        "api.openalex.org": FakeResponse(200,
            _json_bytes({"open_access": {"is_oa": False}, "best_oa_location": None,
                         "abstract_inverted_index": None}),
            "application/json"),
        # Unpaywall: ingen PDF
        "api.unpaywall.org": FakeResponse(200,
            _json_bytes({"best_oa_location": None, "oa_locations": []}),
            "application/json"),
        # CORE: inget
        "api.core.ac.uk": FakeResponse(200, _json_bytes({"results": []}), "application/json"),
        # Semantic Scholar: inget
        "api.semanticscholar.org": FakeResponse(200,
            _json_bytes({"paperId": "x", "openAccessPdf": None}), "application/json"),
        # Direct URL: 403
        "publisher.com": FakeResponse(403, b"", "", "https://publisher.com/article"),
        # Wayback API
        "archive.org/wayback": FakeResponse(200,
            _wayback_resp(archived), "application/json"),
        # Wayback content (HTML, inte PDF – undviker att behöva bygga giltig PDF i testet)
        "web.archive.org": FakeResponse(200, _html_bytes(), "text/html"),
    })

    fetcher, _ = _fetcher(http, level="delbar", tmp_path=tmp_path)
    source = {
        "n": 7,
        "doi": "10.1234/test",
        "source_id": "openalex:W1",
        "title": "Test Paper",
        "abstract": "An abstract.",
        "url": "https://publisher.com/article",
        "authors": ["A. Author"],
        "year": 2020,
        "database": "openalex",
        "source_type": "peer-reviewed",
        "country_codes": [],
        "institutions": [],
        "read_level": "sammanfattning",
        "read_note": "Fulltext inte hämtad än.",
        "text_path": None,
        "quotes": [],
        "relevance": {"role": None, "why": None, "similarity": None},
        "quality": {"citations": None, "age_years": None, "assessment": None},
    }
    fetcher.fetch(source)
    assert source["fetch"]["route"] == "wayback"
    assert source["read_level"] == "fulltext"
