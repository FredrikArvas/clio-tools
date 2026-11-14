"""
fulltext_fetcher.py
Fulltextkedjan, sprint FT0 (PLAN_fulltext_v1.0.md avsnitt 5): steg 1–4.

För varje källa prövas vägarna i ordning tills en ger fulltext:

    1. OpenAlex   best_oa_location.pdf_url, annars landningssidan om källan är öppen
    2. Unpaywall  url_for_pdf (kräver CLIO_CONTACT_EMAIL, hoppas annars över)
    3. CORE       fullText i svaret eller downloadUrl
    4. Direkt     källans egen URL

PDF extraheras med PyMuPDF och HTML med trafilatura. Hela texten sparas som
`kallor/k<nn>.md` i körkatalogen, ett utdrag på högst 8 000 tecken läggs i
`fetch.excerpt`, och läsnivån sätts enligt planens avsnitt 5.1 punkt 7.

Hållning mot källorna:
    - Ett avslag (403, 401, 429 …) är ett svar. Inga omförsök, ingen förfalskad
      webbläsaridentitet, inga omvägar. Avslaget skrivs i `fetch.error` och `read_note`.
    - Högst två anrop per sekund och värd (CORE utan nyckel: ett per sex sekunder).
    - En tidsgräns per källa som beror på nivån (snabb 5 s, standard 15 s, delbar 60 s).
    - Kontaktadressen skickas bara till Unpaywall och hamnar aldrig i loggar eller filer.

Modulen gör inga modellanrop och kastar inte undantag för nätverksfel.

Environment:
    CLIO_CONTACT_EMAIL  – krävs för Unpaywall-steget
    CORE_API_KEY        – valfri; höjer CORE:s anropsgräns
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlsplit

import source_model
from contact import contact_email, redact

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "1.0.0"

USER_AGENT = "clio-research/2.0 (automatiserad forskningsinsamling)"

OPENALEX_WORKS = "https://api.openalex.org/works"
UNPAYWALL_API = "https://api.unpaywall.org/v2"
CORE_SEARCH = "https://api.core.ac.uk/v3/search/works"

STEPS_BY_LEVEL: dict[str, tuple[str, ...]] = {
    "snabb": ("openalex",),
    "standard": ("openalex", "unpaywall", "core", "direct"),
    "delbar": ("openalex", "unpaywall", "core", "direct"),  # steg 5–6 (Wayback, Semantic Scholar) kommer i FT1
}
SECONDS_BY_LEVEL: dict[str, float] = {"snabb": 5.0, "standard": 15.0, "delbar": 60.0}

FULLTEXT_MIN_WORDS = 500      # ≥ 500 ord → fulltext
USABLE_MIN_WORDS = 100        # 100–499 ord → sammanfattning eller kort dokument; under 100 räknas som misslyckat
EXCERPT_MAX_CHARS = source_model.EXCERPT_MAX_CHARS
EXCERPT_HEAD_CHARS = 5000
MAX_BYTES = 40 * 1024 * 1024
REQUEST_TIMEOUT = 20.0
MIN_INTERVAL = 0.5            # sekunder mellan anrop till samma värd
CORE_INTERVAL_NO_KEY = 6.0
MAX_CANDIDATES_PER_STEP = 3

# Värdar som inte hämtas automatiskt (PLAN_fulltext avsnitt 3.2).
DENIED_HOSTS = ("researchgate.net", "sci-hub", "libgen")

_REFERENCES_RE = re.compile(
    r"^\s*(\d+\.?\s*)?(references|bibliography|works cited|literature cited|referenser|litteratur)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CLOSING_RE = re.compile(
    r"^\s*(\d+\.?\s*)?(conclusions?|concluding remarks|discussion|discussion and conclusions?|"
    r"summary and conclusions?|slutsatser?|diskussion)\b.{0,60}$",
    re.IGNORECASE | re.MULTILINE,
)

log = logging.getLogger(__name__)


# ── HTTP ──────────────────────────────────────────────────────────────────────

class FetchTimeout(Exception):
    """Anropet hann inte klart inom tidsgränsen."""


class FetchFailed(Exception):
    """Anropet gick inte att genomföra (nätverksfel, för stor fil)."""


@dataclass
class HttpResult:
    status: int
    content: bytes = b""
    content_type: str = ""
    final_url: str = ""    # adressen efter omdirigeringar; bara värdnamnet används


class Http:
    """Tunn klient ovanpå requests. Byts mot en fejk i testerna.

    Följer omdirigeringar men gör inga omförsök och ändrar aldrig identitet.
    """

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
            timeout: float = REQUEST_TIMEOUT, deadline: float | None = None) -> HttpResult:
        import requests

        send = {"User-Agent": USER_AGENT, **(headers or {})}
        try:
            with requests.get(url, params=params, headers=send, stream=True,
                              timeout=(min(10.0, timeout), timeout), allow_redirects=True) as resp:
                if resp.status_code != 200:
                    return HttpResult(resp.status_code, final_url=resp.url or "")
                chunks, size = [], 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if deadline is not None and time.monotonic() > deadline:
                        raise FetchTimeout()
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchFailed(f"filen är större än {MAX_BYTES // (1024 * 1024)} MB")
                    chunks.append(chunk)
                return HttpResult(200, b"".join(chunks), resp.headers.get("Content-Type", ""), resp.url or "")
        except requests.Timeout as e:
            raise FetchTimeout() from e
        except requests.RequestException as e:
            # Bara feltypen: meddelandet kan innehålla anropets URL.
            raise FetchFailed(type(e).__name__) from e


# ── Extraktion ────────────────────────────────────────────────────────────────

def is_pdf(content: bytes, content_type: str = "") -> bool:
    """Avgör om svaret är en PDF, på innehållet i första hand."""
    return content[:1024].lstrip().startswith(b"%PDF") or "application/pdf" in content_type.lower()


def extract_pdf(content: bytes) -> str:
    """Löptext ur en PDF med PyMuPDF. Tom sträng när PDF:en saknar textlager.

    Raises:
        ValueError: om innehållet inte går att öppna som PDF.
    """
    import fitz

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        raise ValueError(f"går inte att öppna som PDF ({type(e).__name__})") from e
    try:
        pages = [page.get_text() for page in doc]
    finally:
        doc.close()
    return _tidy("\n\n".join(pages))


def extract_html(content: bytes) -> str:
    """Huvudtexten ur en HTML-sida med trafilatura. Tom sträng när inget hittas."""
    import trafilatura

    text = trafilatura.extract(content, include_tables=True, include_comments=False)
    return _tidy(text or "")


def _tidy(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def word_count(text: str) -> int:
    return len(text.split())


def make_excerpt(text: str, limit: int = EXCERPT_MAX_CHARS) -> str:
    """Prioritetsutdrag: början (sammanfattning, inledning) och slutsatsdelen.

    Litteraturlistan skärs bort först. Finns en rubrik för slutsats eller diskussion
    tas slutdelen därifrån, annars de sista tecknen före litteraturlistan.
    Resultatet är aldrig längre än `limit`.
    """
    text = text.strip()
    if len(text) <= limit:
        return text

    body = text
    refs = [m for m in _REFERENCES_RE.finditer(text) if m.start() > len(text) * 0.4]
    if refs:
        body = text[:refs[-1].start()].rstrip()
    if len(body) <= limit:
        return body

    marker = "\n\n[…]\n\n"
    head_len = min(EXCERPT_HEAD_CHARS, limit - len(marker) - 500)
    tail_len = limit - head_len - len(marker)
    head = body[:head_len].rstrip()

    closings = [m for m in _CLOSING_RE.finditer(body) if m.start() >= head_len]
    if closings:
        tail = body[closings[-1].start():closings[-1].start() + tail_len]
        # En slutsatsrubrik långt in i texten kan ge ett kort stycke; ta då den sista rubriken före.
        if len(tail) < tail_len // 2 and len(closings) > 1:
            tail = body[closings[-2].start():closings[-2].start() + tail_len]
    else:
        tail = body[-tail_len:]
    return (head + marker + tail.strip())[:limit]


# ── Läsnivå ───────────────────────────────────────────────────────────────────

def decide_read_level(words: int, kind: str | None, abstract: str | None,
                      text_chars: int = 0, attempted: bool = True) -> tuple[str, str | None]:
    """Läsnivå enligt PLAN_fulltext avsnitt 5.1 punkt 7. Returnerar (nivå, skäl).

    Args:
        words:      Antal ord i den extraherade texten (0 om inget hämtades).
        kind:       "pdf" eller "html" för den hämtade texten, None om inget hämtades.
        abstract:   Källans sammanfattning ur metadata, om den finns.
        text_chars: Antal tecken i den extraherade texten.
        attempted:  Om det fanns någon digital väg att pröva över huvud taget.
    """
    abstract = (abstract or "").strip()
    if words >= FULLTEXT_MIN_WORDS:
        return "fulltext", None
    if words >= USABLE_MIN_WORDS:
        if abstract and text_chars <= len(abstract) * 1.3:
            return "sammanfattning", f"Den hämtade texten ({words} ord) är inte längre än sammanfattningen."
        if kind == "html":
            return "sammanfattning", f"Webbsidan gav bara {words} ord, troligen bara sammanfattningen."
        return "fulltext", f"Kort dokument ({words} ord)."
    if abstract:
        return "sammanfattning", "Fulltext gick inte att hämta; sammanfattningen kommer ur metadata."
    if attempted:
        return "bara titel", "Fulltext gick inte att hämta och sammanfattning saknas."
    return "ej åtkomlig", "Ingen digital väg att pröva: källan saknar DOI och URL."


# ── Kedjan ────────────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    route: str
    url: str | None = None
    license: str | None = None
    inline_text: str | None = None    # CORE lämnar ibland texten direkt i svaret


@dataclass
class _Result:
    route: str
    text: str
    kind: str
    words: int
    url: str | None
    license: str | None


@dataclass
class _Context:
    deadline: float
    failures: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)
    tried: set[str] = field(default_factory=set)
    license: str | None = None
    attempted: bool = False
    best: _Result | None = None


class _OutOfTime(Exception):
    pass


class FulltextFetcher:
    """Kör fulltextkedjan för källor i en körkatalog.

    Args:
        run_dir: Körkatalogen; texterna hamnar i `<run_dir>/kallor/`.
        level:   snabb | standard | delbar. Styr vilka steg som körs och tidsgränsen.
        http:    Klient med `get(url, params, headers, timeout, deadline)`; standard är `Http()`.
        clock, sleep: Tidsfunktioner, utbytbara i tester.
    """

    def __init__(self, run_dir: Path, level: str = "standard", http=None,
                 clock=time.monotonic, sleep=time.sleep):
        if level not in STEPS_BY_LEVEL:
            raise ValueError(f"Okänd nivå {level!r}; väntade en av {', '.join(STEPS_BY_LEVEL)}")
        self.run_dir = Path(run_dir)
        self.level = level
        self.http = http or Http()
        self.clock = clock
        self.sleep = sleep
        self._last_call: dict[str, float] = {}
        self._warned_no_contact = False

    # ── Publikt ───────────────────────────────────────────────────────────────

    def fetch_all(self, sources: list[dict]) -> list[dict]:
        """Kör kedjan för varje källa i tur och ordning. Returnerar samma lista."""
        for source in sources:
            self.fetch(source)
        return sources

    def fetch(self, source: dict) -> dict:
        """Försök hämta fulltext för en källa och fyll i `fetch`, läsnivå och `text_path`.

        Källan ändras på plats och returneras. Nätverksfel kastas inte utan skrivs
        i `fetch.error` och `read_note`.

        Raises:
            source_model.SourceError: om källan saknar `n` (behövs för filnamnet).
        """
        text_path = source_model.text_path_for(source.get("n"))
        ctx = _Context(deadline=self.clock() + SECONDS_BY_LEVEL[self.level])
        # Finns DOI eller URL finns det en digital väg, även om nivån inte prövar alla steg.
        ctx.attempted = bool(source.get("doi") or source.get("url"))

        steps = {
            "openalex": self._step_openalex,
            "unpaywall": self._step_unpaywall,
            "core": self._step_core,
            "direct": self._step_direct,
        }
        try:
            for name in STEPS_BY_LEVEL[self.level]:
                if self._done(ctx):
                    break
                for cand in steps[name](source, ctx)[:MAX_CANDIDATES_PER_STEP]:
                    if self._done(ctx):
                        break
                    self._try(cand, ctx)
        except _OutOfTime:
            ctx.failures.append(f"tidsgräns: {SECONDS_BY_LEVEL[self.level]:.0f} s per källa uppnådd")

        self._finish(source, ctx, text_path)
        return source

    # ── Steg 1–4 ──────────────────────────────────────────────────────────────

    def _step_openalex(self, source: dict, ctx: _Context) -> list[Candidate]:
        doi = source.get("doi")
        source_id = source.get("source_id") or ""
        if source_id.startswith("openalex:W"):
            key = source_id.split(":", 1)[1]
        elif doi:
            key = f"doi:{doi}"
        else:
            ctx.skips.append("openalex: varken DOI eller OpenAlex-id")
            return []

        params = {"select": "id,best_oa_location,open_access,abstract_inverted_index"}
        data = self._get_json("openalex", f"{OPENALEX_WORKS}/{quote(key, safe=':/')}", ctx, params=params)
        if data is None:
            return []

        if not source.get("abstract"):
            abstract = _abstract_from_index(data.get("abstract_inverted_index"))
            if abstract:
                source["abstract"] = abstract

        oa = data.get("open_access") or {}
        best = data.get("best_oa_location") or {}
        ctx.license = best.get("license") or (oa.get("oa_status") if oa.get("oa_status") in ("bronze", "closed") else None)
        if not oa.get("is_oa"):
            ctx.license = "closed"
            ctx.skips.append("openalex: källan är inte öppen enligt OpenAlex")
            return []
        if best.get("pdf_url"):
            return [Candidate("openalex_pdf", best["pdf_url"], ctx.license)]
        if best.get("landing_page_url"):
            # Ingen PDF-länk men öppen: landningssidan hämtas som en direkt URL.
            return [Candidate("direct_url", best["landing_page_url"], ctx.license)]
        ctx.skips.append("openalex: öppen men utan länk")
        return []

    def _step_unpaywall(self, source: dict, ctx: _Context) -> list[Candidate]:
        doi = source.get("doi")
        if not doi:
            ctx.skips.append("unpaywall: källan saknar DOI")
            return []
        email = contact_email()
        if not email:
            if not self._warned_no_contact:
                log.info("[fulltext] Unpaywall hoppas över: kontaktadressen är inte satt i miljön")
                self._warned_no_contact = True
            ctx.skips.append("unpaywall: överhoppad, kontaktadress saknas i miljön")
            return []

        data = self._get_json("unpaywall", f"{UNPAYWALL_API}/{quote(doi, safe='/')}", ctx, params={"email": email})
        if data is None:
            return []
        locations = [data.get("best_oa_location") or {}] + list(data.get("oa_locations") or [])
        candidates = []
        for loc in locations:
            url = loc.get("url_for_pdf") if isinstance(loc, dict) else None
            if url and url not in [c.url for c in candidates]:
                candidates.append(Candidate("unpaywall", url, loc.get("license")))
        if not candidates:
            ctx.skips.append("unpaywall: ingen PDF-länk")
        return candidates

    def _step_core(self, source: dict, ctx: _Context) -> list[Candidate]:
        doi, title = source.get("doi"), source.get("title") or ""
        if doi:
            query = f'doi:"{doi}"'
        elif title:
            query = f'title:"{title.replace(chr(34), " ")}"'
        else:
            return []
        key = os.environ.get("CORE_API_KEY", "").strip()
        headers = {"Authorization": f"Bearer {key}"} if key else None
        data = self._get_json("core", CORE_SEARCH, ctx, params={"q": query, "limit": 3}, headers=headers,
                              interval=MIN_INTERVAL if key else CORE_INTERVAL_NO_KEY)
        if data is None:
            return []

        candidates = []
        for item in data.get("results") or []:
            if not isinstance(item, dict) or not _same_work(item, doi, title):
                continue
            if isinstance(item.get("fullText"), str) and word_count(item["fullText"]) >= USABLE_MIN_WORDS:
                candidates.append(Candidate("core", None, None, inline_text=item["fullText"]))
            elif item.get("downloadUrl"):
                candidates.append(Candidate("core", item["downloadUrl"]))
        if not candidates:
            ctx.skips.append("core: ingen fulltext för källan")
        return candidates

    def _step_direct(self, source: dict, ctx: _Context) -> list[Candidate]:
        url = source.get("url") or (f"https://doi.org/{source['doi']}" if source.get("doi") else None)
        if not url:
            ctx.skips.append("direkt: källan saknar URL")
            return []
        return [Candidate("direct_url", url)]

    # ── Hämtning ──────────────────────────────────────────────────────────────

    def _done(self, ctx: _Context) -> bool:
        return ctx.best is not None and ctx.best.words >= FULLTEXT_MIN_WORDS

    def _pace(self, host: str, ctx: _Context, interval: float = MIN_INTERVAL) -> float:
        """Vänta ut värdens takt. Returnerar sekunder som återstår av källans tidsgräns."""
        now = self.clock()
        wait = max(0.0, self._last_call.get(host, -1e9) + interval - now)
        if now + wait >= ctx.deadline:
            raise _OutOfTime()
        if wait > 0:
            self.sleep(wait)
        self._last_call[host] = self.clock()
        return ctx.deadline - self.clock()

    def _get(self, label: str, url: str, ctx: _Context, *, params=None, headers=None,
             interval: float = MIN_INTERVAL) -> HttpResult | None:
        """Ett anrop, utan omförsök. Returnerar None och antecknar felet om det inte gav 200."""
        host = _host(url)
        remaining = self._pace(host, ctx, interval)
        try:
            result = self.http.get(url, params=params, headers=headers,
                                   timeout=min(REQUEST_TIMEOUT, max(remaining, 1.0)), deadline=ctx.deadline)
        except FetchTimeout:
            ctx.failures.append(f"{label}: tidsgräns ({host})")
            return None
        except FetchFailed as e:
            ctx.failures.append(redact(f"{label}: {e} ({host})"))
            return None
        if result.status != 200:
            # Efter en omdirigering (doi.org → utgivaren) är det slutvärden som vägrade.
            ctx.failures.append(f"{label}: HTTP {result.status} ({_host(result.final_url or url)})")
            return None
        return result

    def _get_json(self, label: str, url: str, ctx: _Context, **kwargs) -> dict | None:
        import json

        result = self._get(label, url, ctx, **kwargs)
        if result is None:
            return None
        try:
            data = json.loads(result.content.decode("utf-8", errors="replace"))
        except ValueError:
            ctx.failures.append(f"{label}: svaret var inte JSON ({_host(url)})")
            return None
        if not isinstance(data, dict):
            ctx.failures.append(f"{label}: oväntat svar ({_host(url)})")
            return None
        return data

    def _try(self, cand: Candidate, ctx: _Context) -> None:
        """Hämta och extrahera en kandidat. Bättre resultat än det hittills bästa sparas i ctx."""
        if cand.inline_text is not None:
            self._keep(_Result(cand.route, _tidy(cand.inline_text), "pdf", word_count(cand.inline_text),
                               None, cand.license), ctx)
            return

        url = cand.url or ""
        host = _host(url)
        if url in ctx.tried:
            return
        ctx.tried.add(url)
        if any(denied in host for denied in DENIED_HOSTS):
            ctx.failures.append(f"{cand.route}: {host} hämtas inte automatiskt")
            return

        result = self._get(cand.route, url, ctx)
        if result is None:
            return
        host = _host(result.final_url or url)
        try:
            if is_pdf(result.content, result.content_type):
                kind, text = "pdf", extract_pdf(result.content)
            else:
                kind, text = "html", extract_html(result.content)
        except ValueError as e:
            ctx.failures.append(f"{cand.route}: {e} ({host})")
            return

        words = word_count(text)
        if words == 0:
            what = "tom text efter extraktion (skannad PDF utan textlager?)" if kind == "pdf" else "ingen text gick att extrahera ur sidan"
            ctx.failures.append(f"{cand.route}: {what} ({host})")
            return
        if words < USABLE_MIN_WORDS:
            ctx.failures.append(f"{cand.route}: bara {words} ord ({host})")
            return
        self._keep(_Result(cand.route, text, kind, words, url, cand.license), ctx)

    def _keep(self, result: _Result, ctx: _Context) -> None:
        if ctx.best is None or result.words > ctx.best.words:
            ctx.best = result

    # ── Resultat ──────────────────────────────────────────────────────────────

    def _finish(self, source: dict, ctx: _Context, text_path: str) -> None:
        best = ctx.best
        error = redact("; ".join(ctx.failures)) if ctx.failures else None
        license_ = (best.license if best and best.license else ctx.license) or "unknown"

        if best is not None:
            self._save_text(source, best, text_path, license_)
            level, why = decide_read_level(best.words, best.kind, source.get("abstract"), len(best.text))
            source["text_path"] = text_path
            source["fetch"] = {
                "route": best.route, "license": license_, "chars": len(best.text),
                "excerpt": make_excerpt(best.text), "error": error,
            }
        else:
            level, why = decide_read_level(0, None, source.get("abstract"), attempted=ctx.attempted)
            source["text_path"] = None
            source["fetch"] = {"route": "none", "license": license_, "chars": 0, "excerpt": "", "error": error}

        notes = [why] if why else []
        if ctx.failures:
            notes.append("Misslyckade försök: " + "; ".join(ctx.failures) + ".")
        if level != "fulltext" and ctx.skips:
            notes.append("Steg utan försök eller träff: " + "; ".join(ctx.skips) + ".")
        source["read_level"] = level
        source["read_note"] = redact(" ".join(notes)) if notes else None

        log.info("[fulltext] k%02d: %s via %s (%d tecken)%s", source["n"], level, source["fetch"]["route"],
                 source["fetch"]["chars"], f" – {error}" if error else "")

    def _save_text(self, source: dict, best: _Result, text_path: str, license_: str) -> None:
        path = self.run_dir / text_path
        path.parent.mkdir(parents=True, exist_ok=True)
        header = [
            f"# [{source['n']}] {source.get('title') or ''}".rstrip(),
            "",
            f"- Källa: {redact(best.url) if best.url else 'text ur CORE:s API-svar'}",
            f"- Väg: {best.route}",
            f"- Licens: {license_}",
            f"- Hämtad: {date.today().isoformat()}",
            f"- Omfång: {len(best.text)} tecken, {best.words} ord",
            "",
            "---",
            "",
        ]
        path.write_text("\n".join(header) + best.text + "\n", encoding="utf-8")


def fetch_fulltexts(sources: list[dict], run_dir: Path, level: str = "standard", http=None) -> list[dict]:
    """Kör fulltextkedjan för alla källor. Bekvämlighetsfunktion runt `FulltextFetcher`."""
    return FulltextFetcher(run_dir, level=level, http=http).fetch_all(sources)


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _host(url: str) -> str:
    return (urlsplit(url).hostname or "okänd värd").lower()


def _abstract_from_index(inverted: dict | None) -> str | None:
    """Bygg sammanfattningen ur OpenAlex `abstract_inverted_index`."""
    if not isinstance(inverted, dict) or not inverted:
        return None
    try:
        positions = {pos: word for word, places in inverted.items() for pos in places}
        return " ".join(positions[i] for i in sorted(positions)) or None
    except (TypeError, ValueError):
        return None


def _same_work(item: dict, doi: str | None, title: str) -> bool:
    """Säkerställ att en CORE-träff är samma verk: samma DOI, eller exakt samma titel."""
    item_doi = source_model.normalize_doi(item.get("doi"))
    if doi and item_doi:
        return item_doi == doi.lower()
    return bool(title) and _norm_title(item.get("title")) == _norm_title(title)


def _norm_title(title) -> str:
    return re.sub(r"[^a-z0-9åäö]+", " ", str(title or "").lower()).strip()
