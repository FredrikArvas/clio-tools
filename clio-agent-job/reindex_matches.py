"""
reindex_matches.py
Indexerar om historiska artiklar mot alla aktiva profiler — utan att skicka mail.

Hämtar artiklar från Odoo (clio.job.article), försöker re-fetcha brödtext,
kör analyze() per profil × artikel och skriver träffar till clio.job.match.

Användning:
    python reindex_matches.py                     # Bara is_matched=True (87 st)
    python reindex_matches.py --all               # Alla 300 artiklar
    python reindex_matches.py --no-fetch          # Hoppa över URL-hämtning (titel räcker)
    python reindex_matches.py --dry-run           # Visa utan att skriva
    python reindex_matches.py --profile ulrika@example.com  # En specifik profil
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_BASE_DIR = Path(__file__).parent
_ROOT_DIR = _BASE_DIR.parent
_SOURCES_DIR = _BASE_DIR / "sources"

for _p in [str(_BASE_DIR), str(_SOURCES_DIR), str(_ROOT_DIR), str(_ROOT_DIR / "clio-core")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT_DIR / ".env")
    load_dotenv(_BASE_DIR / ".env")
except ImportError:
    pass


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _fetch_body(url: str, timeout: int = 8) -> str:
    """
    Försöker hämta brödtext från en URL.
    Returnerar '' vid fel (paywall, timeout, 404).
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (clio-reindex/1.0)"}
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        # Plocka ut <article> eller <main> om det finns, annars <body>
        container = soup.find("article") or soup.find("main") or soup.body
        if not container:
            return ""
        text = container.get_text(separator=" ", strip=True)
        return text[:3000]  # Begränsa till 3 000 tecken
    except Exception:
        return ""


def _odoo_article_to_article(row: dict, body: str = "") -> "Article":
    """Bygger ett Article-objekt från en clio.job.article Odoo-rad."""
    from source_base import Article
    from datetime import datetime

    first_seen = row.get("first_seen") or ""
    if isinstance(first_seen, str) and first_seen:
        try:
            published = datetime.strptime(first_seen[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            published = None
    elif isinstance(first_seen, datetime):
        published = first_seen
    else:
        published = None

    return Article(
        url=row.get("url") or "",
        title=row.get("title") or "",
        source=row.get("source") or "",
        published=published,
        body_snippet=body,
    )


def _write_match(env, profile_id: int, article, result, first_seen_str: str) -> bool:
    """Skapar en clio.job.match-post. Returnerar True om det lyckades."""
    try:
        env["clio.job.match"].create({
            "profile_id":         profile_id,
            "article_url":        article.url,
            "article_title":      (article.title or "")[:255],
            "signal_type":        result.signal_type or "",
            "match_score":        int(result.match_score),
            "recommended_action": result.recommended_action or "",
            "sent_at":            first_seen_str or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        })
        return True
    except Exception as exc:
        print(f"    [FEL] Kunde inte spara match: {exc}")
        return False


# ── Huvudfunktion ─────────────────────────────────────────────────────────────

def reindex(
    only_matched: bool = True,
    dry_run: bool = False,
    no_fetch: bool = False,
    profile_filter: str | None = None,
    threshold: int = 50,
    model: str = "claude-haiku-4-5-20251001",
) -> None:
    from clio_odoo import connect
    from odoo_reader import load_profiles
    from analyzer import analyze

    print("[reindex] Ansluter till Odoo...")
    try:
        env = connect()
    except Exception as e:
        print(f"[FEL] Kunde inte ansluta till Odoo: {e}", file=sys.stderr)
        sys.exit(1)

    # Hämta artiklar
    domain = [("is_matched", "=", True)] if only_matched else []
    article_fields = ["article_id", "url", "title", "source", "first_seen", "match_score"]
    print(f"[reindex] Hämtar artiklar från Odoo {'(is_matched=True)' if only_matched else '(alla)'}...")
    odoo_articles = env["clio.job.article"].search_read(domain, article_fields, order="first_seen asc")
    print(f"[reindex] {len(odoo_articles)} artiklar att bearbeta.")

    if not odoo_articles:
        print("[reindex] Inga artiklar — avslutar.")
        return

    # Hämta profiler
    print("[reindex] Laddar profiler från Odoo...")
    profiles = load_profiles(partner_email=profile_filter)
    if not profiles:
        print("[FEL] Inga aktiva profiler hittades.", file=sys.stderr)
        sys.exit(1)
    print(f"[reindex] {len(profiles)} profil(er): {', '.join(p['name'] for p in profiles)}")

    # Kontrollera vilka (artikel_id, profile_id) redan finns i clio.job.match
    print("[reindex] Kontrollerar befintliga matchningar i Odoo...")
    existing_matches = env["clio.job.match"].search_read(
        [], ["article_url", "profile_id"]
    )
    existing_set: set[tuple[str, int]] = {
        (m["article_url"], m["profile_id"][0] if isinstance(m["profile_id"], list) else m["profile_id"])
        for m in existing_matches
        if m.get("article_url") and m.get("profile_id")
    }
    print(f"[reindex] {len(existing_set)} befintliga matchningar (skippas automatiskt).")

    # Räkna statistik
    total_analyzed = 0
    total_matched = 0
    total_skipped = 0
    total_fetch_ok = 0
    total_fetch_fail = 0

    print(f"\n[reindex] Startar analys {'(dry-run)' if dry_run else ''}...\n")

    for i, row in enumerate(odoo_articles, 1):
        url = row.get("url") or ""
        title = row.get("title") or "(ingen rubrik)"
        first_seen = row.get("first_seen") or ""
        if isinstance(first_seen, str):
            first_seen_str = first_seen[:19].replace("T", " ")
        else:
            first_seen_str = str(first_seen)[:19]

        print(f"  [{i:>3}/{len(odoo_articles)}] {title[:65]}")

        # Re-fetcha brödtext
        body = ""
        if not no_fetch and url:
            body = _fetch_body(url)
            if body:
                total_fetch_ok += 1
                print(f"          URL OK ({len(body)} tecken)")
            else:
                total_fetch_fail += 1
                print(f"          URL misslyckades — kör på titel")

        article = _odoo_article_to_article(row, body=body)

        # Analysera mot varje profil
        for profile in profiles:
            profile_id = profile.get("_odoo_profile_id")
            if not profile_id:
                continue

            # Skippa redan befintliga
            if (url, profile_id) in existing_set:
                total_skipped += 1
                continue

            total_analyzed += 1
            result = analyze(article, profile, model=model)

            if result.error:
                print(f"    [{profile['name']}] FEL: {result.error}")
                continue

            if result.match_score >= threshold and result.is_relevant:
                total_matched += 1
                print(f"    [{profile['name']}] ✓ score={result.match_score} ({result.signal_type})")
                if not dry_run:
                    _write_match(env, profile_id, article, result, first_seen_str)
            else:
                print(f"    [{profile['name']}] — score={result.match_score} (under tröskel)")

            # Kort paus för att inte hammra API:et
            time.sleep(0.3)

        print()

    # Sammanfattning
    print("=" * 60)
    print(f"Artiklar bearbetade:    {len(odoo_articles)}")
    print(f"Profiler:               {len(profiles)}")
    print(f"URL-hämtning OK:        {total_fetch_ok}")
    print(f"URL-hämtning misslyckad:{total_fetch_fail}")
    print(f"Analyser körda:         {total_analyzed}")
    print(f"Matchningar hittade:    {total_matched}")
    print(f"Redan befintliga:       {total_skipped}")
    if dry_run:
        print("\n[DRY-RUN] Inga poster skapade.")
    else:
        print(f"\n{total_matched} matchningar sparade i clio.job.match.")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Indexera om artiklar mot profiler")
    p.add_argument("--all", dest="all_articles", action="store_true",
                   help="Bearbeta alla artiklar (default: bara is_matched=True)")
    p.add_argument("--dry-run", action="store_true",
                   help="Visa utan att spara")
    p.add_argument("--no-fetch", action="store_true",
                   help="Hoppa över URL-hämtning — kör på titel")
    p.add_argument("--profile", default=None,
                   help="Filtrera på specifik e-postadress")
    p.add_argument("--threshold", type=int, default=50,
                   help="Matchningströskel (default: 50)")
    p.add_argument("--model", default="claude-haiku-4-5-20251001",
                   help="Claude-modell")
    args = p.parse_args()

    reindex(
        only_matched=not args.all_articles,
        dry_run=args.dry_run,
        no_fetch=args.no_fetch,
        profile_filter=args.profile,
        threshold=args.threshold,
        model=args.model,
    )
