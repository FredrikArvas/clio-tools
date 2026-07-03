"""
ingest_uap_tracking.py — Indexerar UAP-encounters från Odoo (uapdb) till
Qdrant-collection vigil_ufo.

Kör:
  python3 ingest_uap_tracking.py            # inkrementell (hoppar oförändrade)
  python3 ingest_uap_tracking.py --force    # re-indexerar alla
  python3 ingest_uap_tracking.py --dry-run  # visar utan att skriva

Kräver OPENAI_API_KEY, QDRANT_HOST/PORT i .env (clio-rag/ eller clio-tools/).
Odoo-inloggning läses från ODOO_USER/ODOO_PASSWORD i .env.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

ODOO_URL      = os.getenv("ODOO_URL",      "http://localhost:8069")
ODOO_DB       = os.getenv("ODOO_UAP_DB",   "uapdb")
ODOO_USER     = os.getenv("ODOO_USER",     "")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")

COLLECTION_NAME = "vigil_ufo"
EMBEDDING_MODEL = "text-embedding-3-small"
SOURCE_NAME     = "UAP Tracking"

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

FETCH_FIELDS = [
    "id", "encounter_id", "encounter_guid",
    "title_en", "title_original",
    "description_en", "description_original", "description_sv",
    "country_id", "location",
    "date_observed",
    "encounter_class", "discourse_level", "official_response",
    "language_original", "status",
    "research_notes",
]


# ---------------------------------------------------------------------------
# Odoo helpers
# ---------------------------------------------------------------------------

def fetch_encounters() -> list[dict]:
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        sys.exit("[uap-ingest] FEL: Odoo-inloggning misslyckades — kontrollera ODOO_USER/ODOO_PASSWORD")

    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    total = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "uap.encounter", "search_count", [[]])
    print(f"[uap-ingest] {total} encounters i Odoo ({ODOO_DB})")

    all_records: list[dict] = []
    batch_size = 200
    for offset in range(0, total, batch_size):
        recs = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "uap.encounter", "search_read",
            [[]],
            {"fields": FETCH_FIELDS, "limit": batch_size, "offset": offset},
        )
        all_records.extend(recs)
        print(f"[uap-ingest]   hämtade {len(all_records)}/{total} ...")

    return all_records


# ---------------------------------------------------------------------------
# Chunk-byggare
# ---------------------------------------------------------------------------

def _str(val) -> str:
    """Normalisera Odoo-fältvärde till sträng."""
    if not val or val is False:
        return ""
    if isinstance(val, (list, tuple)):
        return str(val[1]) if len(val) > 1 else ""
    return str(val).strip()


def build_chunk(rec: dict) -> tuple[str, dict]:
    """Returnerar (chunk_text, payload). chunk_text används för embedding."""
    encounter_id     = _str(rec.get("encounter_id"))
    title_en         = _str(rec.get("title_en"))
    title_original   = _str(rec.get("title_original"))
    description_en   = _str(rec.get("description_en"))
    description_orig = _str(rec.get("description_original"))
    country          = _str(rec.get("country_id"))
    location         = _str(rec.get("location"))
    date_observed    = _str(rec.get("date_observed"))
    enc_class        = _str(rec.get("encounter_class"))
    discourse        = _str(rec.get("discourse_level"))
    official         = _str(rec.get("official_response"))
    language         = _str(rec.get("language_original"))
    status           = _str(rec.get("status"))
    research_notes   = _str(rec.get("research_notes"))

    display_title = title_en or title_original or encounter_id

    # --- Chunk-text ---
    parts = [f"UAP Encounter: {encounter_id}"]
    if display_title != encounter_id:
        parts.append(f"Title: {display_title}")
    if title_original and title_original != display_title:
        parts.append(f"Original title: {title_original}")

    meta = []
    if country:
        meta.append(f"Country: {country}")
    if location:
        meta.append(f"Location: {location}")
    if date_observed:
        meta.append(f"Date: {date_observed}")
    if meta:
        parts.append(" | ".join(meta))

    cls_parts = []
    if enc_class:
        cls_parts.append(f"Encounter class: {enc_class}")
    if discourse:
        cls_parts.append(f"Discourse level: {discourse}")
    if official:
        cls_parts.append(f"Official response: {official}")
    if cls_parts:
        parts.append(" | ".join(cls_parts))

    if description_en:
        parts.append(f"\nDESCRIPTION:\n{description_en}")
    elif description_orig:
        parts.append(f"\nDESCRIPTION (original):\n{description_orig}")

    if research_notes:
        notes_trunc = research_notes[:900]
        if len(research_notes) > 900:
            notes_trunc += " [...]"
        parts.append(f"\nRESEARCH NOTES:\n{notes_trunc}")

    chunk_text = "\n".join(p for p in parts if p).strip()

    # --- Payload ---
    payload: dict = {
        "encounter_id":      encounter_id,
        "title":             display_title,
        "country":           country or None,
        "location":          location or None,
        "date_observed":     date_observed or None,
        "encounter_class":   enc_class or None,
        "discourse_level":   discourse or None,
        "official_response": official or None,
        "language":          language or None,
        "status":            status or None,
        "source_name":       SOURCE_NAME,
        "indexed_at":        datetime.now(timezone.utc).isoformat(),
    }
    if title_original and title_original != display_title:
        payload["title_original"] = title_original
    if description_en:
        payload["description_en"] = description_en[:500]

    payload = {k: v for k, v in payload.items() if v is not None}
    return chunk_text, payload


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def encounter_uuid(encounter_id: str) -> str:
    """Deterministiskt UUID v5 — samma encounter_id ger alltid samma Qdrant-punkt-ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"uap_tracking:{encounter_id}"))


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

def load_existing_hashes(client: QdrantClient) -> dict[str, str]:
    """Returnerar {encounter_id: source_hash} för befintliga UAP Tracking-punkter."""
    existing: dict[str, str] = {}
    offset = None
    filt = Filter(must=[
        FieldCondition(key="source_name", match=MatchValue(value=SOURCE_NAME))
    ])
    while True:
        batch, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=filt,
            limit=250,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for pt in batch:
            eid = pt.payload.get("encounter_id", "")
            h   = pt.payload.get("source_hash", "")
            if eid:
                existing[eid] = h
        if offset is None:
            break
    return existing


# ---------------------------------------------------------------------------
# Huvud-pipeline
# ---------------------------------------------------------------------------

def run(force: bool = False, dry_run: bool = False) -> None:
    records = fetch_encounters()
    records = [r for r in records if _str(r.get("encounter_id"))]
    print(f"[uap-ingest] {len(records)} encounters med encounter_id")

    if dry_run:
        print("[uap-ingest] --- DRY RUN (inget skrivs) ---")
        for r in records[:8]:
            eid   = _str(r.get("encounter_id"))
            title = _str(r.get("title_en")) or _str(r.get("title_original")) or eid
            txt, _ = build_chunk(r)
            print(f"  {eid} | {title[:60]} | chunk={len(txt)} tecken")
        return

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    openai = OpenAI()

    existing = {} if force else load_existing_hashes(client)
    print(f"[uap-ingest] {len(existing)} befintliga UAP Tracking-punkter i Qdrant")

    points: list[PointStruct] = []
    skipped = 0
    new_count = 0

    for rec in records:
        encounter_id = _str(rec.get("encounter_id"))
        chunk_text, payload = build_chunk(rec)

        if not chunk_text:
            continue

        h = sha256(chunk_text)
        if not force and existing.get(encounter_id) == h:
            skipped += 1
            continue

        resp   = openai.embeddings.create(input=[chunk_text], model=EMBEDDING_MODEL)
        vector = resp.data[0].embedding

        payload["source_hash"] = h

        points.append(PointStruct(
            id      = encounter_uuid(encounter_id),
            vector  = vector,
            payload = payload,
        ))
        new_count += 1

        if len(points) >= 50:
            client.upsert(collection_name=COLLECTION_NAME, points=points)
            print(f"[uap-ingest]   upsert {new_count}/{len(records)} ...")
            points = []

    if points:
        client.upsert(collection_name=COLLECTION_NAME, points=points)

    print(f"[uap-ingest] Klar.")
    print(f"  Nya/uppdaterade : {new_count}")
    print(f"  Oförändrade     : {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexera UAP encounters (Odoo uapdb) -> vigil_ufo")
    parser.add_argument("--force",   action="store_true", help="Re-indexera alla")
    parser.add_argument("--dry-run", action="store_true", help="Visa utan att skriva")
    args = parser.parse_args()
    run(force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
