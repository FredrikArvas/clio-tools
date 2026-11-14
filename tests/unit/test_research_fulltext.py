"""
test_research_fulltext.py — Enhetstester för fulltextkedjan (fulltext_fetcher.py), spår 1.

Inga nätverksanrop: HTTP-klienten ersätts av en fejk med förbestämda svar, och
klockan av en räknare. PDF:erna byggs i minnet med PyMuPDF.
"""

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import fulltext_fetcher as ff  # noqa: E402
import source_model as sm  # noqa: E402

EMAIL = "kontakt.person@example.org"
DOI = "10.1000/xyz"
OPENALEX_URL = "https://api.openalex.org/works/doi:10.1000/xyz"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/10.1000/xyz"
CORE_URL = "https://api.core.ac.uk/v3/search/works"
PDF_URL = "https://arkiv.example.org/a.pdf"
UPW_PDF_URL = "https://repo.example.net/b.pdf"
LANDING_URL = "https://utgivare.example.com/artikel"


# ── Hjälpmedel ────────────────────────────────────────────────────────────────

def make_pdf(words: int) -> bytes:
    """En PDF med `words` ord löptext (tom PDF om words == 0)."""
    import fitz

    doc = fitz.open()
    remaining = words
    while True:
        page = doc.new_page()
        chunk = min(remaining, 200)
        if chunk:
            text = " ".join(f"ord{i}" for i in range(chunk))
            page.insert_textbox(fitz.Rect(40, 40, 555, 800), text, fontsize=8)
        remaining -= chunk
        if remaining <= 0:
            break
    data = doc.tobytes()
    doc.close()
    return data


def make_html(words: int) -> bytes:
    body = "".join(f"<p>{' '.join(f'ord{p}x{i}' for i in range(50))}.</p>" for p in range(words // 50))
    return f"<html><head><title>Artikel</title></head><body><article><h1>Artikel</h1>{body}</article></body></html>".encode()


def json_result(payload: dict) -> ff.HttpResult:
    return ff.HttpResult(200, json.dumps(payload).encode(), "application/json")


def openalex_reply(pdf_url=PDF_URL, landing=LANDING_URL, is_oa=True, license_="cc-by", abstract=None):
    index = {word: [i] for i, word in enumerate(abstract.split())} if abstract else None
    return json_result({
        "id": "https://openalex.org/W1",
        "open_access": {"is_oa": is_oa, "oa_status": "gold" if is_oa else "closed"},
        "best_oa_location": {"pdf_url": pdf_url, "landing_page_url": landing, "license": license_} if is_oa else None,
        "abstract_inverted_index": index,
    })


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeHttp:
    """Svarar utifrån URL-prefix. Värdet är ett HttpResult, ett undantag eller en funktion."""

    def __init__(self, routes: dict, clock: FakeClock | None = None, seconds_per_call: float = 0.0):
        self.routes = routes
        self.calls = []
        self.clock = clock
        self.seconds_per_call = seconds_per_call

    def get(self, url, *, params=None, headers=None, timeout=None, deadline=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if self.clock:
            self.clock.now += self.seconds_per_call
        for prefix, reply in self.routes.items():
            if url.startswith(prefix):
                if isinstance(reply, Exception):
                    raise reply
                return reply(url, params) if callable(reply) else reply
        return ff.HttpResult(404)

    def hosts(self):
        return [ff._host(c["url"]) for c in self.calls]


def make_source(n=3, **overrides) -> dict:
    source = sm.from_raw_hit({
        "title": "A study of things", "database": "crossref", "external_id": DOI,
        "doi": DOI, "url": LANDING_URL, "abstract": "Kort sammanfattning ur metadata.", "year": 2020,
    })
    source["n"] = n
    source.update(overrides)
    return source


def make_fetcher(tmp_path, routes, level="standard", seconds_per_call=0.0):
    clock = FakeClock()
    http = FakeHttp(routes, clock, seconds_per_call)
    return ff.FulltextFetcher(tmp_path, level=level, http=http, clock=clock, sleep=clock.sleep), http, clock


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("CLIO_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("CORE_API_KEY", raising=False)


# ── Lyckad väg ────────────────────────────────────────────────────────────────

def test_openalex_pdf_gives_fulltext_and_stops_the_chain(tmp_path):
    fetcher, http, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.HttpResult(200, make_pdf(1200), "application/pdf"),
    })
    source = fetcher.fetch(make_source())

    assert http.hosts() == ["api.openalex.org", "arkiv.example.org"]
    assert source["read_level"] == "fulltext"
    assert source["read_note"] is None
    assert source["text_path"] == "kallor/k03.md"
    assert source["fetch"]["route"] == "openalex_pdf"
    assert source["fetch"]["license"] == "cc-by"
    assert source["fetch"]["error"] is None
    assert 0 < len(source["fetch"]["excerpt"]) <= 8000

    saved = (tmp_path / "kallor" / "k03.md").read_text(encoding="utf-8")
    assert saved.startswith("# [3] A study of things")
    assert "ord199" in saved
    assert source["fetch"]["chars"] > 5000
    sm.validate_source(source, complete=False)


def test_chain_order_and_every_refusal_is_recorded_without_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIO_CONTACT_EMAIL", EMAIL)
    fetcher, http, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.HttpResult(403),
        UNPAYWALL_URL: json_result({"best_oa_location": {"url_for_pdf": UPW_PDF_URL, "license": "cc-by-nc"}}),
        UPW_PDF_URL: ff.HttpResult(403),
        CORE_URL: json_result({"results": []}),
        LANDING_URL: ff.HttpResult(200, make_html(900), "text/html"),
    })
    source = fetcher.fetch(make_source())

    assert http.hosts() == [
        "api.openalex.org", "arkiv.example.org", "api.unpaywall.org",
        "repo.example.net", "api.core.ac.uk", "utgivare.example.com",
    ]
    urls = [c["url"] for c in http.calls]
    assert len(urls) == len(set(urls)), "ett avslag får inte ge omförsök"
    assert source["fetch"]["route"] == "direct_url"
    assert source["read_level"] == "fulltext"
    assert source["fetch"]["error"] == (
        "openalex_pdf: HTTP 403 (arkiv.example.org); unpaywall: HTTP 403 (repo.example.net)"
    )
    assert "HTTP 403 (arkiv.example.org)" in source["read_note"]
    assert "HTTP 403 (repo.example.net)" in source["read_note"]


def test_openalex_landing_page_used_when_open_without_pdf(tmp_path):
    fetcher, http, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(pdf_url=None),
        LANDING_URL: ff.HttpResult(200, make_html(800), "text/html"),
    })
    source = fetcher.fetch(make_source())
    assert source["fetch"]["route"] == "direct_url"
    assert source["read_level"] == "fulltext"
    assert http.hosts() == ["api.openalex.org", "utgivare.example.com"]


def test_core_inline_fulltext_and_wrong_title_rejected(tmp_path):
    text = " ".join(f"ord{i}" for i in range(700))
    fetcher, http, _ = make_fetcher(tmp_path, {
        CORE_URL: json_result({"results": [
            {"title": "Något helt annat", "fullText": text},
            {"title": "A Study of Things.", "fullText": text},
        ]}),
    })
    source = fetcher.fetch(make_source(doi=None, url=None, source_id="core:1"))
    assert source["fetch"]["route"] == "core"
    assert source["read_level"] == "fulltext"
    assert http.calls[0]["params"]["q"] == 'title:"A study of things"'

    fetcher, _, _ = make_fetcher(tmp_path, {
        CORE_URL: json_result({"results": [{"title": "Något helt annat", "fullText": text}]}),
    })
    source = fetcher.fetch(make_source(n=4, doi=None, url=None, source_id="core:2", abstract=None))
    assert source["fetch"]["route"] == "none"
    assert source["read_level"] == "ej åtkomlig"


def test_openalex_fills_missing_abstract(tmp_path):
    fetcher, _, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(is_oa=False, abstract="Sammanfattning från OpenAlex här"),
    }, level="snabb")
    source = fetcher.fetch(make_source(abstract=None))
    assert source["abstract"] == "Sammanfattning från OpenAlex här"
    assert source["read_level"] == "sammanfattning"
    assert source["fetch"]["license"] == "closed"


# ── Misslyckad väg ────────────────────────────────────────────────────────────

def test_403_everywhere_with_abstract_gives_sammanfattning(tmp_path):
    fetcher, http, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.HttpResult(403),
        CORE_URL: ff.HttpResult(429),
        LANDING_URL: ff.HttpResult(403),
    })
    source = fetcher.fetch(make_source())

    assert source["read_level"] == "sammanfattning"
    assert source["text_path"] is None
    assert source["fetch"] == {
        "route": "none", "license": "cc-by", "chars": 0, "excerpt": "",
        "error": "openalex_pdf: HTTP 403 (arkiv.example.org); core: HTTP 429 (api.core.ac.uk); "
                 "direct_url: HTTP 403 (utgivare.example.com)",
    }
    assert "Misslyckade försök" in source["read_note"]
    assert "unpaywall: överhoppad" in source["read_note"]
    assert not (tmp_path / "kallor").exists()
    assert len(http.calls) == 4
    sm.validate_source(source, complete=False)


def test_403_without_abstract_gives_bara_titel(tmp_path):
    fetcher, _, _ = make_fetcher(tmp_path, {OPENALEX_URL: openalex_reply(), PDF_URL: ff.HttpResult(403)})
    source = fetcher.fetch(make_source(abstract=None, read_level="bara titel"))
    assert source["read_level"] == "bara titel"
    assert "HTTP 403" in source["fetch"]["error"]
    sm.validate_source(source, complete=False)


def test_no_doi_and_no_url_is_ej_atkomlig_without_any_call_but_core(tmp_path):
    fetcher, http, _ = make_fetcher(tmp_path, {CORE_URL: json_result({"results": []})})
    source = fetcher.fetch(make_source(doi=None, url=None, abstract=None, source_id="webb:1"))
    assert source["read_level"] == "ej åtkomlig"
    assert source["fetch"]["route"] == "none"
    assert source["fetch"]["error"] is None
    assert "saknar DOI och URL" in source["read_note"]
    assert http.hosts() == ["api.core.ac.uk"]
    sm.validate_source(source, complete=False)


def test_timeout_on_one_route_is_recorded_and_chain_continues(tmp_path):
    fetcher, _, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.FetchTimeout(),
        CORE_URL: json_result({"results": []}),
        LANDING_URL: ff.HttpResult(200, make_html(700), "text/html"),
    })
    source = fetcher.fetch(make_source())
    assert source["fetch"]["route"] == "direct_url"
    assert source["fetch"]["error"] == "openalex_pdf: tidsgräns (arkiv.example.org)"


def test_time_budget_per_source_stops_the_chain(tmp_path):
    fetcher, http, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.HttpResult(403),
        LANDING_URL: ff.HttpResult(200, make_html(700), "text/html"),
    }, seconds_per_call=9.0)
    source = fetcher.fetch(make_source())

    assert http.hosts() == ["api.openalex.org", "arkiv.example.org"]
    assert source["fetch"]["route"] == "none"
    assert "tidsgräns: 15 s per källa uppnådd" in source["fetch"]["error"]
    assert "tidsgräns" in source["read_note"]
    assert http.calls[1]["timeout"] <= 6.0


def test_empty_pdf_is_a_recorded_failure_and_next_route_is_tried(tmp_path):
    fetcher, _, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.HttpResult(200, make_pdf(0), "application/pdf"),
        CORE_URL: json_result({"results": []}),
        LANDING_URL: ff.HttpResult(403),
    })
    source = fetcher.fetch(make_source())
    assert source["fetch"]["route"] == "none"
    assert "openalex_pdf: tom text efter extraktion" in source["fetch"]["error"]
    assert "direct_url: HTTP 403" in source["fetch"]["error"]
    assert source["read_level"] == "sammanfattning"


def test_broken_pdf_and_non_json_api_reply_are_recorded(tmp_path):
    fetcher, _, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: ff.HttpResult(200, b"<html>underhall</html>", "text/html"),
        CORE_URL: json_result({"results": []}),
        LANDING_URL: ff.HttpResult(200, b"%PDF-1.4 trasig", "application/pdf"),
    })
    source = fetcher.fetch(make_source())
    assert "openalex: svaret var inte JSON" in source["fetch"]["error"]
    assert "direct_url: går inte att öppna som PDF" in source["fetch"]["error"] or "tom text" in source["fetch"]["error"]
    assert source["fetch"]["route"] == "none"


def test_short_html_is_saved_but_read_level_is_sammanfattning(tmp_path):
    fetcher, _, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(pdf_url=None),
        CORE_URL: json_result({"results": []}),
        LANDING_URL: ff.HttpResult(200, make_html(200), "text/html"),
    })
    source = fetcher.fetch(make_source())
    assert source["read_level"] == "sammanfattning"
    assert "troligen bara sammanfattningen" in source["read_note"]
    assert source["text_path"] == "kallor/k03.md"
    assert (tmp_path / "kallor" / "k03.md").exists()
    sm.validate_source(source, complete=False)


def test_refusal_names_the_host_that_refused_after_redirect(tmp_path):
    doi_url = "https://doi.org/10.1000/xyz"
    fetcher, _, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(pdf_url=None, landing=doi_url),
        CORE_URL: json_result({"results": []}),
        doi_url: ff.HttpResult(403, final_url=f"https://dl.example-utgivare.org/doi/full/10.1000/xyz?email={EMAIL}"),
    })
    source = fetcher.fetch(make_source(url=doi_url))
    assert source["fetch"]["error"] == "direct_url: HTTP 403 (dl.example-utgivare.org)"
    assert EMAIL not in json.dumps(source)


def test_denied_host_is_never_fetched(tmp_path):
    rg = "https://www.researchgate.net/publication/1"
    fetcher, http, _ = make_fetcher(tmp_path, {CORE_URL: json_result({"results": []})})
    source = fetcher.fetch(make_source(doi=None, url=rg))
    assert "www.researchgate.net" not in http.hosts()
    assert "hämtas inte automatiskt" in source["fetch"]["error"]


def test_source_without_n_is_rejected(tmp_path):
    fetcher, _, _ = make_fetcher(tmp_path, {})
    with pytest.raises(sm.SourceError):
        fetcher.fetch(make_source(n=None))


def test_unknown_level_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Okänd nivå"):
        ff.FulltextFetcher(tmp_path, level="extra")


# ── Nivå och takt ─────────────────────────────────────────────────────────────

def test_level_snabb_only_asks_openalex(tmp_path):
    fetcher, http, _ = make_fetcher(tmp_path, {OPENALEX_URL: openalex_reply(), PDF_URL: ff.HttpResult(403)}, level="snabb")
    source = fetcher.fetch(make_source())
    assert http.hosts() == ["api.openalex.org", "arkiv.example.org"]
    assert source["read_level"] == "sammanfattning"


def test_same_host_is_paced_between_sources(tmp_path):
    fetcher, _, clock = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.HttpResult(200, make_pdf(600), "application/pdf"),
    })
    fetcher.fetch_all([make_source(n=1), make_source(n=2)])
    # Källa 2 väntar ut OpenAlex; därefter har en halv sekund redan gått för PDF-värden.
    assert clock.sleeps == [pytest.approx(0.5)]


def test_core_without_key_is_paced_slower_and_sends_no_auth(tmp_path):
    fetcher, http, clock = make_fetcher(tmp_path, {CORE_URL: json_result({"results": []})})
    fetcher.fetch_all([
        make_source(n=1, doi=None, url=None, source_id="webb:1"),
        make_source(n=2, doi=None, url=None, source_id="webb:2"),
    ])
    assert clock.sleeps == [pytest.approx(6.0)]
    assert all(c["headers"] is None for c in http.calls)


def test_real_client_identifies_itself_honestly():
    assert "clio-research" in ff.USER_AGENT
    assert "Mozilla" not in ff.USER_AGENT


# ── Kontaktadressen ───────────────────────────────────────────────────────────

def test_unpaywall_is_skipped_without_contact_and_log_has_no_address(tmp_path, caplog):
    fetcher, http, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.HttpResult(403),
        CORE_URL: json_result({"results": []}),
        LANDING_URL: ff.HttpResult(403),
    })
    with caplog.at_level(logging.DEBUG):
        source = fetcher.fetch(make_source())
    assert "api.unpaywall.org" not in http.hosts()
    assert "Unpaywall hoppas över" in caplog.text
    assert "@" not in caplog.text
    assert "unpaywall: överhoppad, kontaktadress saknas i miljön" in source["read_note"]


def test_contact_address_reaches_unpaywall_but_never_logs_or_files(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CLIO_CONTACT_EMAIL", EMAIL)
    leaky = ff.FetchFailed(f"ConnectionError for {UNPAYWALL_URL}?email={EMAIL} and {EMAIL.replace('@', '%40')}")
    fetcher, http, _ = make_fetcher(tmp_path, {
        OPENALEX_URL: openalex_reply(),
        PDF_URL: ff.HttpResult(403),
        UNPAYWALL_URL: leaky,
        CORE_URL: json_result({"results": []}),
        LANDING_URL: ff.HttpResult(200, make_html(700), "text/html"),
    })
    with caplog.at_level(logging.DEBUG):
        first = fetcher.fetch(make_source(n=1))
        second = fetcher.fetch(make_source(n=2, url="https://annan.example.org/x"))
    sm.assign_numbers([first, second])
    for src in (first, second):
        src["relevance"] = {"role": "direkt", "why": "Hör till frågan.", "similarity": 0.5}
    sm.write_sources(tmp_path, [first, second])

    unpaywall_calls = [c for c in http.calls if "unpaywall" in c["url"]]
    assert unpaywall_calls and all(c["params"] == {"email": EMAIL} for c in unpaywall_calls)
    assert all(EMAIL not in c["url"] for c in http.calls)
    others = [c for c in http.calls if "unpaywall" not in c["url"]]
    assert all(EMAIL not in json.dumps([c["params"], c["headers"]]) for c in others)

    assert "unpaywall:" in first["fetch"]["error"]
    for needle in (EMAIL, EMAIL.replace("@", "%40"), "example.org?email"):
        assert needle not in caplog.text
        assert needle not in json.dumps([first, second], ensure_ascii=False)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert needle not in path.read_text(encoding="utf-8"), path


def test_real_http_client_hides_request_url_in_errors(monkeypatch):
    import requests

    def boom(url, **kwargs):
        raise requests.ConnectionError(f"HTTPSConnectionPool: {url}?email={EMAIL}")

    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(ff.FetchFailed) as exc:
        ff.Http().get(UNPAYWALL_URL, params={"email": EMAIL})
    assert str(exc.value) == "ConnectionError"

    def slow(url, **kwargs):
        raise requests.ReadTimeout("för långsamt")

    monkeypatch.setattr(requests, "get", slow)
    with pytest.raises(ff.FetchTimeout):
        ff.Http().get(PDF_URL)


def test_real_http_client_sends_honest_user_agent_and_returns_refusal(monkeypatch):
    import requests

    seen = {}

    class Resp:
        status_code = 403
        headers = {}
        url = "https://utgivare.example.com/slutadress"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        return Resp()

    monkeypatch.setattr(requests, "get", fake_get)
    result = ff.Http().get(PDF_URL)
    assert result.status == 403
    assert result.final_url == "https://utgivare.example.com/slutadress"
    assert seen["headers"]["User-Agent"] == ff.USER_AGENT


# ── Läsnivå och utdrag ────────────────────────────────────────────────────────

@pytest.mark.parametrize("words, kind, abstract, chars, attempted, expected", [
    (500, "pdf", None, 3000, True, "fulltext"),
    (10600, "pdf", "abc", 70000, True, "fulltext"),
    (499, "pdf", None, 3000, True, "fulltext"),
    (217, "html", None, 1645, True, "sammanfattning"),
    (217, "pdf", "x" * 1500, 1645, True, "sammanfattning"),
    (100, "html", None, 600, True, "sammanfattning"),
    (99, "html", "Sammanfattning.", 500, True, "sammanfattning"),
    (0, None, "Sammanfattning.", 0, True, "sammanfattning"),
    (0, None, None, 0, True, "bara titel"),
    (0, None, "  ", 0, True, "bara titel"),
    (0, None, None, 0, False, "ej åtkomlig"),
])
def test_decide_read_level(words, kind, abstract, chars, attempted, expected):
    level, why = ff.decide_read_level(words, kind, abstract, chars, attempted)
    assert level == expected
    assert level in sm.READ_LEVELS
    if level != "fulltext":
        assert why


def test_short_pdf_is_fulltext_with_note():
    assert ff.decide_read_level(300, "pdf", None, 2000) == ("fulltext", "Kort dokument (300 ord).")


def test_excerpt_takes_start_and_conclusions_and_drops_references():
    intro = "Abstract\n" + "inledning " * 1500
    middle = "\n\n3. Method\n" + "metod " * 4000
    closing = "\n\n5. Conclusions\n" + "slutsats " * 200
    refs = "\n\nReferences\n" + "Hynek, J. A. (1972). The UFO Experience. " * 300
    excerpt = ff.make_excerpt(intro + middle + closing + refs)

    assert len(excerpt) <= 8000
    assert excerpt.startswith("Abstract")
    assert "5. Conclusions" in excerpt
    assert "slutsats" in excerpt
    assert "Hynek" not in excerpt
    assert "[…]" in excerpt


def test_excerpt_of_short_text_is_the_whole_text_and_long_text_without_headings_is_capped():
    assert ff.make_excerpt("  kort text  ") == "kort text"
    excerpt = ff.make_excerpt("ord " * 10000)
    assert len(excerpt) <= 8000
    assert "[…]" in excerpt


def test_is_pdf_sniffs_content_before_header():
    assert ff.is_pdf(b"%PDF-1.7 ...", "text/html")
    assert ff.is_pdf(b"binary", "application/pdf; charset=binary")
    assert not ff.is_pdf(b"<html>", "text/html")
