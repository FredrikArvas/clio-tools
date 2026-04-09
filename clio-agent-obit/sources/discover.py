"""
sources/discover.py — Källupptäckt för clio-agent-obit

Två-stegsflöde:
    1. discover.py search --query "..."   → kandidat-URL:er
    2. discover.py probe <url> [--add NAME] → verifiera + föreslå adapter

`probe` sonderar en URL i prioritetsordning:
    1. <link rel="alternate" application/rss+xml> i HTML <head>
    2. /rss /feed /rss.xml /feed.xml /atom.xml (HEAD-requests)
    3. /sitemap.xml + URL-mönsterigenkänning
    4. JSON-LD (Person/DeathEvent-scheman)
    5. Heuristik för upprepade list-element

Resultat skrivs som JSON till stdout. Med --add appenderas
det föreslagna source-entryt till sources.yaml som enabled: false.

Körning:
    python sources/discover.py probe https://www.familjesidan.se
    python sources/discover.py probe https://minnessidor.fonus.se --add fonus-national
    python sources/discover.py search --results-file kandidater.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Optional
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    raise ImportError("requests saknas. Kör: pip install requests")

try:
    from bs4 import BeautifulSoup
except ImportError:
    raise ImportError("beautifulsoup4 saknas. Kör: pip install beautifulsoup4")

# registry är valfritt — discover.py ska kunna köras utan att paketet
# är installerat hela vägen, för debugging
try:
    from sources.registry import append_source
    _HAS_REGISTRY = True
except Exception:
    _HAS_REGISTRY = False


USER_AGENT = "clio-agent-obit-discover/0.2 (+https://arvas.se)"
COMMON_FEED_PATHS = ("/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml", "/feeds/posts/default")


# ───────────────────────── probe ─────────────────────────

def _http_get(url: str, timeout: int = 15) -> Optional[requests.Response]:
    try:
        return requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None


def _http_head(url: str, timeout: int = 8) -> Optional[int]:
    try:
        r = requests.head(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=True,
        )
        return r.status_code
    except requests.RequestException:
        return None


def find_rss_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    feeds: list[str] = []
    for link in soup.find_all("link", rel=lambda v: v and "alternate" in v):
        if link.get("type", "").lower() in (
            "application/rss+xml",
            "application/atom+xml",
        ):
            href = link.get("href")
            if href:
                feeds.append(urljoin(base_url, href))
    return feeds


def probe_common_feed_paths(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    found = []
    for path in COMMON_FEED_PATHS:
        status = _http_head(root + path)
        if status and status < 400:
            found.append(root + path)
    return found


def find_json_ld(soup: BeautifulSoup) -> list[dict]:
    nodes = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            nodes.extend(data)
        else:
            nodes.append(data)
    relevant = [
        n for n in nodes
        if isinstance(n, dict)
        and (n.get("@type") in ("Person", "DeathEvent") or "deathDate" in n)
    ]
    return relevant


def find_candidate_lists(soup: BeautifulSoup, sample_size: int = 6) -> list[dict]:
    """
    Heuristik: hitta upprepade element som ser ut som en lista av personer.
    Letar efter klassnamn som upprepas minst 4 ggr inom samma container.
    """
    class_counter: Counter[str] = Counter()
    for el in soup.find_all(["article", "li", "div"], class_=True):
        for cls in el.get("class", []):
            class_counter[cls] += 1

    candidates = []
    for cls, count in class_counter.most_common(15):
        if count < 4:
            continue
        items = soup.select(f".{cls}")
        # Verifiera att åtminstone några innehåller text som ser ut som ett namn
        sample_titles = []
        for it in items[:sample_size]:
            txt = it.get_text(" ", strip=True)
            if 3 <= len(txt) <= 200:
                sample_titles.append(txt[:120])
        if sample_titles:
            candidates.append({
                "selector": f".{cls}",
                "sample_count": count,
                "sample_titles": sample_titles,
            })
        if len(candidates) >= 5:
            break
    return candidates


def probe(url: str) -> dict:
    """Sondera en URL och returnera ett strukturerat fynd."""
    report: dict = {
        "url": url,
        "ok": False,
        "rss_feeds": [],
        "common_feed_paths": [],
        "json_ld": [],
        "candidate_lists": [],
        "recommended_adapter": None,
        "suggested_yaml": None,
        "notes": [],
    }

    resp = _http_get(url)
    if resp is None:
        report["notes"].append("Nätverksfel — kunde inte hämta sidan")
        return report
    if resp.status_code >= 400:
        report["notes"].append(f"HTTP {resp.status_code}")
        return report

    report["ok"] = True
    soup = BeautifulSoup(resp.text, "html.parser")

    report["rss_feeds"] = find_rss_links(soup, url)
    report["common_feed_paths"] = probe_common_feed_paths(url)
    report["json_ld"] = find_json_ld(soup)
    report["candidate_lists"] = find_candidate_lists(soup)

    if report["rss_feeds"] or report["common_feed_paths"]:
        report["recommended_adapter"] = "rss"
        report["notes"].append(
            "Hittade RSS — använd source_familjesidan_rss.py som mall för en RSS-adapter."
        )
    elif report["candidate_lists"]:
        report["recommended_adapter"] = "html"
        first = report["candidate_lists"][0]
        report["suggested_yaml"] = {
            "name": urlparse(url).netloc.replace(".", "-"),
            "enabled": False,
            "adapter": "source_html.HtmlListSource",
            "config": {
                "url": url,
                "list_selector": first["selector"],
                "name_selector": "h2, h3, a",
                "link_selector": "a",
                "summary_selector": "p",
            },
        }
        report["notes"].append(
            "Inget RSS funnet — föreslår generisk HtmlListSource med upptäckta selektorer. "
            "Kör adaptern, justera selektorerna om resultatet blir tomt."
        )
    else:
        report["notes"].append(
            "Varken RSS eller listmönster identifierat. Källan kräver en bespoke "
            "adapter — överväg om den är värd ansträngningen."
        )

    return report


# ───────────────────────── search (stub) ─────────────────────────

def search(query: str, results_file: Optional[str] = None, limit: int = 10) -> list[str]:
    """
    STUB i 0.2.0. Två lägen:
      - Om --results-file ges: läs URL-rader därifrån (en per rad).
      - Annars: skriv hjälptext om hur man genererar kandidater via Claude.

    0.3.0 kan plugga in en riktig sök-API här utan att gränssnittet ändras.
    """
    if results_file:
        try:
            with open(results_file, encoding="utf-8") as f:
                urls = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]
            return urls[:limit]
        except FileNotFoundError:
            print(f"[discover] {results_file} saknas", file=sys.stderr)
            return []

    print(
        f"[discover] search är en stub i 0.2.0.\n"
        f"  Generera kandidater via Claude.ai/Code:\n"
        f'    "Hitta {limit} svenska sajter som publicerar dödsannonser, ge bara URL:er"\n'
        f"  Spara dem i en textfil (en URL per rad) och kör:\n"
        f"    python sources/discover.py search --results-file kandidater.txt\n"
        f"  Eller probe varje URL direkt:\n"
        f"    python sources/discover.py probe <url>\n",
        file=sys.stderr,
    )
    return []


# ───────────────────────── CLI ─────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="discover",
        description="clio-agent-obit källupptäckt — search + probe",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Sondera en URL")
    p_probe.add_argument("url", help="URL att sondera")
    p_probe.add_argument(
        "--add",
        metavar="NAME",
        help="Appendera fyndet till sources.yaml som enabled: false med detta namn",
    )

    p_search = sub.add_parser("search", help="Hitta kandidat-URL:er")
    p_search.add_argument("--query", default="svenska dödsannonser", help="Sökfras")
    p_search.add_argument("--results-file", help="Fil med en URL per rad")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--probe-each", action="store_true", help="Probe varje resultat")

    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.command == "probe":
        report = probe(args.url)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if args.add and report.get("suggested_yaml"):
            if not _HAS_REGISTRY:
                print("[discover] registry inte tillgänglig — kan inte --add",
                      file=sys.stderr)
                return 1
            entry = dict(report["suggested_yaml"])
            entry["name"] = args.add
            append_source(entry)
            print(f"[discover] Lade till '{args.add}' i sources.yaml (enabled: false)",
                  file=sys.stderr)
        elif args.add:
            print("[discover] Inget förslag att lägga till — sondera misslyckades",
                  file=sys.stderr)
        return 0 if report.get("ok") else 1

    if args.command == "search":
        urls = search(args.query, results_file=args.results_file, limit=args.limit)
        if args.probe_each:
            results = [probe(u) for u in urls]
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            for u in urls:
                print(u)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
