"""media_connector.py — Insamling av nyhetsartiklar från vigil_ufo (Qdrant) och GDELT DOC 2.0."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Iterator
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_MAX_RECORDS = 250
GDELT_SLEEP = 1.0
VIGIL_SIMILARITY_THRESHOLD = 0.25
VIGIL_TOP_K = 300
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
RSS_CUTOFF_DATE = "2024-06-01"  # Google News RSS har ingen historisk djupning före ca 90 dagar

OUTLET_DOMAINS: dict[str, str] = {
    "Dagens Nyheter": "dn.se",
    "Svenska Dagbladet": "svd.se",
    "SVT Nyheter": "svt.se",
    "The New York Times": "nytimes.com",
    "The Washington Post": "washingtonpost.com",
    "Le Monde": "lemonde.fr",
    "France 24": "france24.com",
    "Folha de S.Paulo": "folha.uol.com.br",
    "O Globo": "oglobo.globo.com",
}

# lang / country / ceid för Google News RSS per outlet-domain
_RSS_CONFIG: dict[str, tuple[str, str, str]] = {
    "dn.se":               ("sv", "SE", "SE:sv"),
    "svd.se":              ("sv", "SE", "SE:sv"),
    "svt.se":              ("sv", "SE", "SE:sv"),
    "nytimes.com":         ("en", "US", "US:en"),
    "washingtonpost.com":  ("en", "US", "US:en"),
    "lemonde.fr":          ("fr", "FR", "FR:fr"),
    "france24.com":        ("fr", "FR", "FR:fr"),
    "folha.uol.com.br":    ("pt", "BR", "BR:pt-419"),
    "oglobo.globo.com":    ("pt", "BR", "BR:pt-419"),
}

_DOMAIN_TO_COUNTRY: dict[str, str] = {
    "dn.se": "SE", "svd.se": "SE", "svt.se": "SE",
    "nytimes.com": "US", "washingtonpost.com": "US",
    "lemonde.fr": "FR", "france24.com": "FR",
    "folha.uol.com.br": "BR", "oglobo.globo.com": "BR",
}

_OUTLET_TO_COUNTRY: dict[str, str] = {
    name: country
    for name, domain in OUTLET_DOMAINS.items()
    for d, country in _DOMAIN_TO_COUNTRY.items()
    if d == domain
}


def collect(protocol: dict) -> list[dict]:
    """Samla artiklar från vigil_ufo och GDELT. Returnerar deduplicerad lista."""
    question = protocol["question"]["natural_language"]

    vigil_articles = _query_vigil_ufo(question)
    logger.info("[media_connector] vigil_ufo: %d artiklar", len(vigil_articles))

    gdelt_articles = _query_gdelt(protocol)
    logger.info("[media_connector] GDELT: %d artiklar", len(gdelt_articles))

    rss_articles = _query_google_news_rss(protocol)
    logger.info("[media_connector] Google News RSS: %d artiklar", len(rss_articles))

    combined = _deduplicate(vigil_articles + gdelt_articles + rss_articles)
    logger.info("[media_connector] Totalt efter deduplicering: %d artiklar", len(combined))
    return combined


# ── vigil_ufo ──────────────────────────────────────────────────────────────────

def _query_vigil_ufo(question: str) -> list[dict]:
    """Sök vigil_ufo Qdrant-collection för mediachunks."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue
    except ImportError:
        logger.warning("[media_connector] qdrant-client saknas — vigil_ufo hoppas över")
        return []

    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))

    try:
        client = QdrantClient(url=f"http://{host}:{port}", check_compatibility=False)
    except Exception as e:
        logger.warning("[media_connector] Qdrant ej tillgänglig: %s", e)
        return []

    query_vector = _embed_text(question)
    if query_vector is None:
        return []

    try:
        result = client.query_points(
            collection_name="vigil_ufo",
            query=query_vector,
            limit=VIGIL_TOP_K,
            score_threshold=VIGIL_SIMILARITY_THRESHOLD,
            query_filter=Filter(
                must=[FieldCondition(key="type", match=MatchValue(value="media_chunk"))]
            ),
        )
    except Exception as e:
        logger.warning("[media_connector] vigil_ufo-sökning misslyckades: %s", e)
        return []

    return [_normalize_vigil_hit(hit) for hit in result.points if _normalize_vigil_hit(hit)]


def _normalize_vigil_hit(hit) -> dict | None:
    p = hit.payload
    title = p.get("title") or p.get("headline") or ""
    snippet = p.get("text") or p.get("body") or p.get("snippet") or ""
    if not title and not snippet:
        return None
    outlet = p.get("source_name") or p.get("outlet") or p.get("source") or "Okänd"
    country = p.get("country") or _OUTLET_TO_COUNTRY.get(outlet, "?")
    article_date = p.get("date") or p.get("published_date") or ""
    return {
        "article_id": _make_id(title, outlet, article_date),
        "title": title,
        "outlet": outlet,
        "country": country,
        "language": p.get("language") or "?",
        "date": article_date,
        "url": p.get("url") or p.get("source_url") or "",
        "snippet": snippet[:800],
        "source": "vigil_ufo",
        "relevance_score": round(hit.score, 4),
    }


# ── GDELT ──────────────────────────────────────────────────────────────────────

def _query_gdelt(protocol: dict) -> list[dict]:
    """Sök GDELT DOC 2.0 per outlet och tidskvartal."""
    scope = protocol.get("scope", {})
    period_start = scope.get("period_start", "2017-12-01")
    period_end = scope.get("period_end", "2026-06-30")
    outlets = _extract_outlets(protocol)
    quarters = list(_quarterly_windows(period_start, period_end))

    articles: list[dict] = []
    total_calls = 0

    for outlet_name, domain in outlets.items():
        for q_start, q_end in quarters:
            new = _gdelt_request(domain, q_start, q_end)
            articles.extend(new)
            total_calls += 1
            time.sleep(GDELT_SLEEP)
            if total_calls % 10 == 0:
                logger.info(
                    "[media_connector] GDELT: %d anrop gjorda, %d artiklar totalt",
                    total_calls, len(articles),
                )

    return articles


def _gdelt_request(domain: str, date_start: str, date_end: str) -> list[dict]:
    query = f'(UAP OR UFO OR "unidentified aerial phenomena") domain:{domain}'
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": GDELT_MAX_RECORDS,
        "startdatetime": date_start,
        "enddatetime": date_end,
        "sort": "DateDesc",
    }

    for attempt in range(3):
        try:
            r = requests.get(GDELT_API_URL, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt * 10)
                continue
            r.raise_for_status()
            data = r.json()
            break
        except requests.RequestException as e:
            if attempt == 2:
                logger.warning(
                    "[media_connector] GDELT misslyckades (%s, %s): %s",
                    domain, date_start, e,
                )
                return []
            time.sleep(2 ** attempt * 5)
    else:
        return []

    outlet = _domain_to_outlet(domain)
    country = _DOMAIN_TO_COUNTRY.get(domain, "?")

    result = []
    for item in data.get("articles") or []:
        title = item.get("title") or ""
        if not title:
            continue
        article_date = _parse_gdelt_date(item.get("seendate") or "")
        result.append({
            "article_id": _make_id(title, outlet, article_date),
            "title": title,
            "outlet": outlet,
            "country": country,
            "language": item.get("language") or "",
            "date": article_date,
            "url": item.get("url") or "",
            "snippet": title,
            "source": "gdelt",
            "relevance_score": None,
        })
    return result


def _extract_outlets(protocol: dict) -> dict[str, str]:
    outlets: dict[str, str] = {}
    for group in protocol.get("sources", {}).get("primary_media", []):
        for outlet in group.get("outlets", []):
            name = outlet.get("name") or ""
            domain = OUTLET_DOMAINS.get(name)
            if domain:
                outlets[name] = domain
            else:
                logger.warning("[media_connector] Ingen domain-mappning för: %s", name)
    return outlets


def _quarterly_windows(start: str, end: str) -> Iterator[tuple[str, str]]:
    """Generera kvartalsvisa (YYYYMMDDHHMMSS, YYYYMMDDHHMMSS) par."""
    dt_start = datetime.strptime(start[:10], "%Y-%m-%d")
    dt_end = datetime.strptime(end[:10], "%Y-%m-%d")

    year, month = dt_start.year, ((dt_start.month - 1) // 3) * 3 + 1
    current = datetime(year, month, 1)

    while current <= dt_end:
        q_end_month = current.month + 2
        q_end_year = current.year + (q_end_month - 1) // 12
        q_end_month = (q_end_month - 1) % 12 + 1
        last_day = _last_day_of_month(q_end_year, q_end_month)
        q_end = datetime(q_end_year, q_end_month, last_day, 23, 59, 59)

        eff_start = max(current, dt_start)
        eff_end = min(q_end, dt_end.replace(hour=23, minute=59, second=59))

        if eff_start <= eff_end:
            yield eff_start.strftime("%Y%m%d%H%M%S"), eff_end.strftime("%Y%m%d%H%M%S")

        next_month = current.month + 3
        current = datetime(current.year + (next_month - 1) // 12, (next_month - 1) % 12 + 1, 1)


def _last_day_of_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


# ── Google News RSS (komplettering 2024-06 → nu) ──────────────────────────────

def _query_google_news_rss(protocol: dict) -> list[dict]:
    """
    Kompletterar GDELT för perioden RSS_CUTOFF_DATE → period_end.
    Hämtar Google News RSS per outlet med UAP/UFO-söktermer.
    Filtrerar på datum i Python eftersom RSS ej stödjer date-range.
    """
    scope = protocol.get("scope", {})
    period_end = scope.get("period_end", "2026-06-30")

    if period_end < RSS_CUTOFF_DATE:
        return []

    outlets = _extract_outlets(protocol)
    articles: list[dict] = []

    for outlet_name, domain in outlets.items():
        new = _rss_request(domain, outlet_name, RSS_CUTOFF_DATE, period_end)
        articles.extend(new)
        time.sleep(0.5)

    return articles


def _rss_request(
    domain: str, outlet_name: str, date_from: str, date_to: str
) -> list[dict]:
    """Hämta och filtrera ett Google News RSS-flöde för ett outlet."""
    lang, country, ceid = _RSS_CONFIG.get(domain, ("en", "US", "US:en"))
    query = f'UAP OR UFO OR "unidentified aerial phenomena" site:{domain}'
    params = {"q": query, "hl": lang, "gl": country, "ceid": ceid}

    for attempt in range(3):
        try:
            r = requests.get(
                GOOGLE_NEWS_RSS_URL,
                params=params,
                timeout=20,
                headers={"User-Agent": "clio-research/1.4 (research tool)"},
            )
            if r.status_code == 429:
                time.sleep(2 ** attempt * 10)
                continue
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                logger.warning("[media_connector] RSS misslyckades (%s): %s", domain, e)
                return []
            time.sleep(2 ** attempt * 5)
    else:
        return []

    return _parse_rss_feed(r.text, outlet_name, domain, date_from, date_to)


def _parse_rss_feed(
    xml_text: str, outlet_name: str, domain: str, date_from: str, date_to: str
) -> list[dict]:
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("[media_connector] RSS XML-parsning misslyckades (%s): %s", domain, e)
        return []

    country = _DOMAIN_TO_COUNTRY.get(domain, "?")
    articles = []

    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        url = item.findtext("link") or item.findtext("guid") or ""
        pub_date_raw = item.findtext("pubDate") or ""

        if not title:
            continue

        article_date = ""
        if pub_date_raw:
            try:
                dt = parsedate_to_datetime(pub_date_raw)
                article_date = dt.strftime("%Y-%m-%d")
            except Exception:
                article_date = ""

        if article_date and not (date_from <= article_date <= date_to):
            continue

        articles.append({
            "article_id": _make_id(title, outlet_name, article_date),
            "title": title,
            "outlet": outlet_name,
            "country": country,
            "language": _RSS_CONFIG.get(domain, ("en",))[0],
            "date": article_date,
            "url": url,
            "snippet": title,
            "source": "google_news_rss",
            "relevance_score": None,
        })

    return articles


# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _deduplicate(articles: list[dict]) -> list[dict]:
    """Deduplicera på article_id. vigil_ufo-poster prioriteras framför GDELT."""
    seen: dict[str, dict] = {}
    for a in articles:
        aid = a["article_id"]
        if aid not in seen or a.get("source") == "vigil_ufo":
            seen[aid] = a
    return list(seen.values())


def _make_id(title: str, outlet: str, date: str) -> str:
    key = f"{(title or '').lower().strip()}|{(outlet or '').lower()}|{(date or '')[:10]}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _parse_gdelt_date(raw: str) -> str:
    try:
        if "T" in raw:
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        return raw[:10]
    except Exception:
        return raw


def _domain_to_outlet(domain: str) -> str:
    for name, d in OUTLET_DOMAINS.items():
        if d == domain:
            return name
    return domain


def _embed_text(text: str) -> list[float] | None:
    try:
        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.embeddings.create(input=[text], model="text-embedding-3-small")
        return resp.data[0].embedding
    except Exception as e:
        logger.warning("[media_connector] Embedding misslyckades: %s", e)
        return None
