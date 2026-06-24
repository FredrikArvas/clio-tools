"""
clio-vigil — journalist_extractor.py
======================================
Extraherar journalistbylines från insamlade bevakningsobjekt och bygger
intresseprofiler via Claude. Resultaten lagras i journalists-tabellen och
synkas till Odoo via odoo_writer.

Flöde:
  vigil_items (indexed/notified) → byline-parser → journalists-tabell
                                 → Claude-profilering → profile-fält

Designbeslut:
  - Upsert-nyckel: (name, publication) — en journalist kan byta namn, men
    name+publication är tillräckligt stabilt för MVP
  - Generiska bylines (Staff, TT, Reuters) filtreras ut tidigt
  - Profilering körs i batcher: max_journalists per anrop
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_HAIKU  = "claude-haiku-4-5-20251001"
MAX_ARTICLES_FOR_PROFILE = 12

# Bylines att ignorera
_SKIP_AUTHORS = {
    "staff", "staff writer", "staff reporter", "editors", "redaktionen",
    "the editors", "associated press", "ap", "tt", "reuters", "afp", "np",
    "admin", "administrator", "unknown", "anonymous",
}


# ---------------------------------------------------------------------------
# Byline-extraktion
# ---------------------------------------------------------------------------

def extract_author_from_entry(entry) -> Optional[str]:
    """Returnerar ett städat journalistnamn från ett feedparser-entry, eller None."""
    candidates = []

    # feedparser: entry.author (sträng) och entry.author_detail (dict)
    if hasattr(entry, "author_detail") and entry.author_detail:
        name = entry.author_detail.get("name", "")
        if name:
            candidates.append(name)

    if hasattr(entry, "author") and entry.author:
        candidates.append(entry.author)

    # Dublin Core: dc:creator
    if hasattr(entry, "tags"):
        for tag in entry.tags:
            if tag.get("scheme", "").endswith("creator"):
                candidates.append(tag.get("term", ""))

    for raw in candidates:
        clean = _clean_name(raw)
        if clean:
            return clean

    return None


def _clean_name(raw: str) -> Optional[str]:
    """Städar ett rånamn. Returnerar None om det inte ser ut som ett personnamn."""
    if not raw:
        return None
    name = raw.strip()
    # Ta bort HTML-taggar
    name = re.sub(r"<[^>]+>", "", name).strip()
    # Om det ser ut som en mailadress
    if "@" in name:
        return None
    # Längdkontroll
    if len(name) < 3 or len(name) > 80:
        return None
    # Generiska bylines
    if name.lower() in _SKIP_AUTHORS:
        return None
    # Bara siffror eller symboler
    if not re.search(r"[a-zA-ZåäöÅÄÖ]", name):
        return None
    return name


# ---------------------------------------------------------------------------
# Databas — journalists och journalist_articles
# ---------------------------------------------------------------------------

def upsert_journalist(
    conn,
    name: str,
    publication: str,
    domain: str,
    item_id: Optional[int] = None,
) -> int:
    """
    Skapar eller uppdaterar en journalist. Returnerar journalist_id.
    Kopplar valfritt ett vigil_item via journalist_articles.
    """
    now = datetime.now(timezone.utc).isoformat()

    row = conn.execute(
        "SELECT id FROM journalists WHERE name = ? AND publication = ?",
        (name, publication),
    ).fetchone()

    if row:
        journalist_id = row["id"]
        conn.execute(
            """UPDATE journalists
               SET article_count = article_count + 1,
                   last_seen_at  = ?,
                   updated_at    = ?
               WHERE id = ?""",
            (now, now, journalist_id),
        )
    else:
        cur = conn.execute(
            """INSERT INTO journalists (name, publication, domain, article_count, last_seen_at)
               VALUES (?, ?, ?, 1, ?)""",
            (name, publication, domain, now),
        )
        journalist_id = cur.lastrowid
        logger.info("Ny journalist: %s @ %s", name, publication)

    if item_id:
        conn.execute(
            """INSERT OR IGNORE INTO journalist_articles (journalist_id, item_id)
               VALUES (?, ?)""",
            (journalist_id, item_id),
        )

    conn.commit()
    return journalist_id


# ---------------------------------------------------------------------------
# Batch-extraktion
# ---------------------------------------------------------------------------

def run_extractor(conn, domain: Optional[str] = None, max_items: int = 200) -> dict:
    """
    Processar vigil_items med state indexed/notified och extraherar bylines.
    Returnerar räknare: {processed, extracted, skipped}
    """
    domain_clause = "AND domain = ?" if domain else ""
    params = [domain] if domain else []

    rows = conn.execute(
        f"""SELECT vi.id, vi.source_name, vi.domain, vi.raw_metadata, vi.title
            FROM vigil_items vi
            WHERE vi.state IN ('indexed','notified','summarized')
              AND vi.id NOT IN (SELECT item_id FROM journalist_articles WHERE item_id IS NOT NULL)
              {domain_clause}
            ORDER BY vi.published_at DESC
            LIMIT ?""",
        params + [max_items],
    ).fetchall()

    counts = {"processed": 0, "extracted": 0, "skipped": 0}

    for row in rows:
        counts["processed"] += 1
        metadata = {}
        try:
            metadata = json.loads(row["raw_metadata"] or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

        author = metadata.get("author")
        if not author:
            counts["skipped"] += 1
            continue

        publication = row["source_name"] or "Okänd"
        upsert_journalist(conn, author, publication, row["domain"], row["id"])
        counts["extracted"] += 1

    logger.info(
        "Byline-extraktion: %d processerade, %d bylines, %d utan byline",
        counts["processed"], counts["extracted"], counts["skipped"],
    )
    return counts


# ---------------------------------------------------------------------------
# Profil-bygge via Claude
# ---------------------------------------------------------------------------

def build_profiles(conn, domain: Optional[str] = None, max_journalists: int = 20) -> dict:
    """
    Bygger intresseprofiler för journalister utan profil via Claude Haiku.
    Returnerar räknare: {built, skipped, failed}
    """
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic-paketet saknas — kör: pip install anthropic")
        return {"built": 0, "skipped": 0, "failed": 0}

    domain_clause = "AND j.domain = ?" if domain else ""
    params = [domain] if domain else []

    journalists = conn.execute(
        f"""SELECT j.id, j.name, j.publication, j.domain, j.article_count
            FROM journalists j
            WHERE (j.profile IS NULL OR j.profile = '')
              AND j.article_count >= 2
              {domain_clause}
            ORDER BY j.article_count DESC
            LIMIT ?""",
        params + [max_journalists],
    ).fetchall()

    counts = {"built": 0, "skipped": 0, "failed": 0}
    client = anthropic.Anthropic()

    for j in journalists:
        articles = conn.execute(
            """SELECT vi.title, vi.summary
               FROM journalist_articles ja
               JOIN vigil_items vi ON vi.id = ja.item_id
               WHERE ja.journalist_id = ?
                 AND vi.title IS NOT NULL
               ORDER BY vi.published_at DESC
               LIMIT ?""",
            (j["id"], MAX_ARTICLES_FOR_PROFILE),
        ).fetchall()

        if not articles:
            counts["skipped"] += 1
            continue

        article_list = "\n".join(
            f"- {a['title']}" + (f": {a['summary'][:120]}" if a["summary"] else "")
            for a in articles
        )

        prompt = (
            f"Du är en PR-strateg. Analysera följande artiklar av journalisten "
            f"{j['name']} ({j['publication']}) och skriv en kort profil (max 150 ord) "
            f"som beskriver:\n"
            f"1. Bevakningsämnen och nyckelord\n"
            f"2. Typisk journalistisk vinkel\n"
            f"3. Rekommenderad approach vid pitching\n\n"
            f"Artiklar:\n{article_list}\n\n"
            f"Svara enbart med profiltexten, inga rubriker."
        )

        try:
            response = client.messages.create(
                model=MODEL_HAIKU,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            profile = response.content[0].text.strip()

            # Extrahera topics (enkel heuristik: ord med stor bokstav, 3+ tecken)
            topics = list({
                w for w in re.findall(r"\b[A-ZÅÄÖ][a-zåäö]{2,}", profile)
                if w not in {"Typisk", "Rekommenderad", "Approach", "Svara"}
            })[:8]

            conn.execute(
                """UPDATE journalists
                   SET profile    = ?,
                       topics     = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (profile, json.dumps(topics, ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat(), j["id"]),
            )
            conn.commit()
            counts["built"] += 1
            logger.info("Profil byggd: %s @ %s", j["name"], j["publication"])

        except Exception as exc:
            logger.error("Profil misslyckades för %s: %s", j["name"], exc)
            counts["failed"] += 1

    return counts
