#!/usr/bin/env python3
"""
detect_republications.py — Hitta och länka återpublicerade avsnitt i clio.media.article.

Algoritm:
1. Hämta alla artiklar med titel (paginerat)
2. Normalisera titeln (lowercase, ta bort emoji/specialtecken, kollapsa whitespace, trunkera)
3. Klustra poster med samma normaliserade titel (minst --min-cluster poster)
4. För varje kluster: äldste icke-aggregator = original, övriga = återpubliceringar
5. Skriv canonical_article_id + repub_note (om inte --dry-run)

Kända aggregatorer (återpublicerar andras innehåll — väljs aldrig som original):
    Multiverse 5D, Multiverse 5D Podcast

Användning:
    python detect_republications.py [--dry-run] [--min-cluster 2] [--reset]
"""

import argparse
import os
import re
import sys
import unicodedata
import xmlrpc.client
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv

# ── Konfiguration ──────────────────────────────────────────────────────────

KNOWN_AGGREGATORS = {
    "Multiverse 5D",
    "Multiverse 5D Podcast",
}

PAGE_SIZE = 500  # poster per XMLRPC-anrop

# ── Normalisering ──────────────────────────────────────────────────────────

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc Symbols & Pictographs
    "\U0001F680-\U0001F6FF"  # Transport & Map
    "\U0001F700-\U0001F77F"  # Alchemical symbols
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)


def normalize_title(title: str) -> str:
    """Normaliserar en titel för jämförelse.
    - Tar bort emoji
    - Konverterar till ASCII (NFKD + encode/decode)
    - Lowercase
    - Tar bort allt som inte är bokstav, siffra eller mellanslag
    - Kollapsar whitespace
    - Trunkerar till 80 tecken
    """
    if not title:
        return ""
    t = _EMOJI_RE.sub("", title)
    # NFKD-normalisering — konverterar ligaturer, accent-tecken etc.
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", errors="ignore").decode("ascii")
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:80]


# ── XMLRPC-hjälpare ────────────────────────────────────────────────────────

def connect(url: str, db: str, user: str, password: str):
    """Returnerar (models-proxy, uid)."""
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, password, {})
    if not uid:
        sys.exit(f"❌ Autentisering misslyckades mot {url} (db={db}, user={user})")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return models, uid


def fetch_all_articles(models, uid, db, password):
    """Hämtar alla artiklar med titel — returnerar lista av dicts."""
    offset = 0
    result = []
    fields = ["id", "title", "source", "published", "canonical_article_id"]
    domain = [["title", "!=", False]]
    while True:
        batch = models.execute_kw(
            db, uid, password,
            "clio.media.article", "search_read",
            [domain],
            {"fields": fields, "limit": PAGE_SIZE, "offset": offset, "order": "id asc"},
        )
        if not batch:
            break
        result.extend(batch)
        offset += len(batch)
        if len(batch) < PAGE_SIZE:
            break
    return result


# ── Klustreringslogik ──────────────────────────────────────────────────────

def published_sort_key(article):
    """Sorteringsnyckel: artiklar utan datum sorteras sist."""
    pub = article.get("published")
    if not pub or pub is False:
        return datetime.max
    if isinstance(pub, str):
        try:
            return datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            return datetime.max
    return datetime.max


def choose_canonical(cluster: list[dict]) -> dict:
    """Väljer originalposten i ett kluster.

    Sortera på published ASC (äldst = original-kandidat).
    Om äldste källan är en känd aggregator: hoppa till näste icke-aggregator.
    Om ingen icke-aggregator finns: välj äldste oavsett.
    """
    sorted_cluster = sorted(cluster, key=published_sort_key)
    for article in sorted_cluster:
        source = (article.get("source") or "").strip()
        if source not in KNOWN_AGGREGATORS:
            return article
    # Alla är aggregatorer — välj ändå äldste
    return sorted_cluster[0]


def build_clusters(articles: list[dict], min_cluster: int) -> list[list[dict]]:
    """Grupperar artiklar på normaliserad titel. Returnerar kluster >= min_cluster."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for a in articles:
        key = normalize_title(a.get("title") or "")
        if not key:
            continue
        buckets[key].append(a)
    return [v for v in buckets.values() if len(v) >= min_cluster]


# ── Huvud ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Visa kluster utan att skriva till Odoo")
    parser.add_argument("--min-cluster", type=int, default=2, metavar="N",
                        help="Ignorera kluster med färre än N poster (default: 2)")
    parser.add_argument("--reset", action="store_true",
                        help="Rensa alla canonical_article_id-kopplingar innan körning")
    args = parser.parse_args()

    # Ladda env
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(env_path)
    url      = os.environ.get("VIGIL_ODOO_URL", "").rstrip("/")
    db       = os.environ.get("VIGIL_ODOO_DB", "")
    user     = os.environ.get("ODOO_USER", "")
    password = os.environ.get("ODOO_PASSWORD", "")

    if not all([url, db, user, password]):
        sys.exit("❌ Saknar VIGIL_ODOO_URL, VIGIL_ODOO_DB, ODOO_USER eller ODOO_PASSWORD i .env")

    print(f"🔌 Ansluter till {url} (db={db}, user={user}) …")
    models, uid = connect(url, db, user, password)

    # Hämta alla artiklar
    print("📥 Hämtar artiklar …")
    articles = fetch_all_articles(models, uid, db, password)
    print(f"   {len(articles)} artiklar med titel funna")

    # Reset om begärt
    if args.reset and not args.dry_run:
        print("🗑  Rensar befintliga canonical_article_id-kopplingar …")
        linked_ids = models.execute_kw(
            db, uid, password,
            "clio.media.article", "search",
            [[["canonical_article_id", "!=", False]]],
        )
        if linked_ids:
            models.execute_kw(
                db, uid, password,
                "clio.media.article", "write",
                [linked_ids, {"canonical_article_id": False, "repub_note": False}],
            )
            print(f"   Rensade {len(linked_ids)} poster")
        # Uppdatera lokala data
        for a in articles:
            if a["id"] in linked_ids:
                a["canonical_article_id"] = False

    # Klustra
    clusters = build_clusters(articles, args.min_cluster)
    print(f"\n🔍 {len(clusters)} kluster med ≥ {args.min_cluster} poster hittade\n")

    total_linked = 0
    skipped_locked = 0

    for i, cluster in enumerate(sorted(clusters, key=len, reverse=True), 1):
        canonical = choose_canonical(cluster)
        repubs = [a for a in cluster if a["id"] != canonical["id"]]

        pub_str = canonical.get("published") or "okänt datum"
        if isinstance(pub_str, str) and "T" in pub_str:
            pub_str = pub_str[:10]

        print(f"Kluster {i:3d} ({len(cluster)} poster):")
        print(f"  ✅ ORIGINAL: [{canonical['id']}] {canonical.get('source','?')} — {canonical.get('title','')[:70]}")
        print(f"              Publicerad: {pub_str}")
        for r in repubs:
            r_pub = r.get("published") or "okänt datum"
            if isinstance(r_pub, str) and "T" in r_pub:
                r_pub = r_pub[:10]
            locked = bool(r.get("canonical_article_id") and not args.reset)
            lock_mark = " [LÅST]" if locked else ""
            print(f"  ↩ REPUB   : [{r['id']}] {r.get('source','?')} — {r.get('title','')[:70]}{lock_mark}")
            print(f"              Publicerad: {r_pub}")

        print()

        if args.dry_run:
            continue

        # Skriv till Odoo
        for r in repubs:
            if r.get("canonical_article_id") and not args.reset:
                # Manuellt låst — rör inte
                skipped_locked += 1
                continue

            note = f"Återpublicering av {canonical.get('source', '?')} ({pub_str})"
            models.execute_kw(
                db, uid, password,
                "clio.media.article", "write",
                [[r["id"]], {
                    "canonical_article_id": canonical["id"],
                    "repub_note": note,
                }],
            )
            total_linked += 1

    # Sammanfattning
    if args.dry_run:
        print(f"🏁 DRY-RUN klar — {len(clusters)} kluster, {sum(len(c)-1 for c in clusters)} möjliga återpubliceringar")
    else:
        print(f"🏁 Klar — {total_linked} poster länkade, {skipped_locked} hoppades över (manuellt låsta)")


if __name__ == "__main__":
    main()
