"""
auto_import.py — clio-uap: Automatisk UAP-observationsimport
=============================================================
Skannar vigil_ufo (media-chunks) efter nya UAP-observationer och
importerar dem till uapdb via semantisk sökning + Claude-klassificering.

Flöde:
  1. SEARCH   — semantisk sökning i vigil_ufo efter observations-kandidater
  2. CLASSIFY — Claude bedömer encounter-typ + tilldelar klassificering
  3. DEDUP    — fuzzy-match + URL-match mot befintliga encounters i Odoo
  4. IMPORT   — skapar uap.encounter med status=pending i Odoo
  5. REINDEX  — kör ingest_uap_tracking.py för att uppdatera vigil_ufo

Kör manuellt:
  cd ~/clio-tools/clio-uap
  python3 auto_import.py [--dry-run] [--max N] [--score-threshold 0.50]

Systemd-timer:
  Koppla till clio-vigil.timer eller skapa separat uap-import.timer.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Sökvägar & miljövariabler
# ---------------------------------------------------------------------------

_BASE_DIR  = Path(__file__).parent           # ~/clio-tools/clio-uap/
_ROOT_DIR  = _BASE_DIR.parent                # ~/clio-tools/
_VIGIL_DIR = _ROOT_DIR / "clio-vigil"        # ~/clio-tools/clio-vigil/
_RAG_DIR   = _ROOT_DIR / "clio-rag"          # ~/clio-tools/clio-rag/

for _p in [str(_ROOT_DIR), str(_BASE_DIR), str(_VIGIL_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT_DIR / ".env", override=True)
    load_dotenv(_BASE_DIR / ".env", override=True)
except ImportError:
    pass

ODOO_URL      = os.getenv("ODOO_URL",      "http://localhost:8069")
ODOO_UAP_DB   = os.getenv("ODOO_UAP_DB",   "uapdb")
ODOO_USER     = os.getenv("ODOO_USER",     "")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")

QDRANT_HOST   = os.getenv("QDRANT_HOST",   "localhost")
QDRANT_PORT   = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION    = "vigil_ufo"
EMBEDDING_MODEL = "text-embedding-3-small"

STATE_FILE = _BASE_DIR / "auto_import_state.json"

# ---------------------------------------------------------------------------
# Sök-queries: målsätter konkreta observationer, ej analys/kommentar
# ---------------------------------------------------------------------------

SEARCH_QUERIES = [
    "UAP sighting witnessed pilot military aircraft encounter close approach",
    "unidentified aerial phenomenon eyewitness account observed object",
    "UFO close encounter physical evidence radar confirmed incident",
    "anomalous object hovering moving observed sky eyewitness report",
    "UAP incident documented official military government investigation",
]

# ---------------------------------------------------------------------------
# Källkarta: vigil_ufo source_name → uap.database namn
# ---------------------------------------------------------------------------
SOURCE_TO_DB_NAME: dict[str, str] = {
    # Lägg till när strukturerade importörer byggs, t.ex.:
    # "NUFORC": "NUFORC — National UFO Reporting Center",
    # Podcasts/media saknar uap.database-post
}

_DB_NAME_CACHE: dict[str, int | None] = {}


def _lookup_db_id(db_name: str) -> int | None:
    """Slår upp uap.database ID via XML-RPC, cachar resultatet."""
    if db_name in _DB_NAME_CACHE:
        return _DB_NAME_CACHE[db_name]
    import xmlrpc.client as _xml
    _m = _xml.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    _c = _xml.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    _uid = _c.authenticate(ODOO_UAP_DB, ODOO_USER, ODOO_PASSWORD, {})
    res = _m.execute_kw(ODOO_UAP_DB, _uid, ODOO_PASSWORD,
        "uap.database", "search_read",
        [[["name", "=", db_name]]], {"fields": ["id"], "limit": 1})
    did = res[0]["id"] if res else None
    _DB_NAME_CACHE[db_name] = did
    return did


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("uap-auto-import")


# ---------------------------------------------------------------------------
# State-cache: undviker re-klassificering av låg-scoring items
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Steg 1: SEARCH — semantisk sökning i vigil_ufo
# ---------------------------------------------------------------------------

def search_candidates(
    score_threshold: float = 0.72,
    top_per_query: int = 20,
) -> list[dict]:
    """
    Sök vigil_ufo med flera observation-queries.
    Returnerar unika media-chunks (ej UAP Tracking) sorterade på score.
    """
    try:
        from openai import OpenAI
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue
    except ImportError as e:
        logger.error(f"Import-fel: {e}")
        return []

    openai_client = OpenAI()
    qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Filtrera bort encounter-chunks (de har source_name="UAP Tracking")
    media_filter = Filter(
        must_not=[
            FieldCondition(
                key="source_name",
                match=MatchValue(value="UAP Tracking"),
            )
        ]
    )

    seen_urls: dict[str, dict] = {}

    for query in SEARCH_QUERIES:
        try:
            resp = openai_client.embeddings.create(
                input=[query],
                model=EMBEDDING_MODEL,
            )
            vector = resp.data[0].embedding
        except Exception as e:
            logger.warning(f"  Embedding-fel för '{query[:40]}': {e}")
            continue

        try:
            result = qdrant.query_points(
                collection_name=COLLECTION,
                query=vector,
                query_filter=media_filter,
                limit=top_per_query,
                score_threshold=score_threshold,
                with_payload=True,
            )
            hits = result.points
        except Exception as e:
            logger.warning(f"  Qdrant-fel: {e}")
            continue

        for hit in hits:
            payload = hit.payload or {}
            source  = payload.get("source_name", "")
            url     = payload.get("url") or payload.get("link") or ""
            title   = payload.get("title") or payload.get("subject") or ""
            key     = url or title  # dedup-nyckel

            if not key:
                continue

            if key not in seen_urls or hit.score > seen_urls[key]["score"]:
                seen_urls[key] = {
                    "url":         url,
                    "title":       title,
                    "content":     (
                        payload.get("text")
                        or payload.get("description")
                        or payload.get("content")
                        or ""
                    ),
                    "source_name": source,
                    "score":       hit.score,
                    "payload":     payload,
                }

    candidates = sorted(seen_urls.values(), key=lambda x: x["score"], reverse=True)
    logger.info(f"[SEARCH] {len(candidates)} unika kandidater hittade")
    return candidates


# ---------------------------------------------------------------------------
# Steg 2: CLASSIFY — Claude-klassificering
# ---------------------------------------------------------------------------

def classify_candidate(candidate: dict) -> dict:
    """Anropar uap_classifier.classify() för en kandidat."""
    from classifiers.uap_classifier import classify
    return classify(
        title=candidate["title"][:200],
        content=candidate["content"][:2000],
    )


# ---------------------------------------------------------------------------
# Steg 3: DEDUP — kontroll mot befintliga Odoo-encounters
# ---------------------------------------------------------------------------

def load_existing_encounters() -> list[dict]:
    """Hämtar befintliga encounters från uapdb via XML-RPC."""
    import xmlrpc.client

    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid    = common.authenticate(ODOO_UAP_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise RuntimeError("Odoo-autentisering misslyckades mot uapdb")

    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    recs   = models.execute_kw(
        ODOO_UAP_DB, uid, ODOO_PASSWORD,
        "uap.encounter", "search_read",
        [[]],
        {"fields": ["encounter_id", "title_en", "research_notes"], "limit": 2000},
    )
    return recs


def _normalize(text: str) -> str:
    """Normalisera sträng för fuzzy-jämförelse."""
    return re.sub(r"\W+", " ", text.lower()).strip()


def is_duplicate(
    candidate: dict,
    existing: list[dict],
    title_threshold: float = 0.85,
) -> bool:
    """
    Returnerar True om kandidaten troligen redan finns i Odoo.
    Kontrollerar: URL i research_notes + fuzzy titel-match.
    """
    url   = candidate.get("url", "")
    title = _normalize(candidate.get("title", ""))

    for enc in existing:
        notes = enc.get("research_notes") or ""

        # Exakt URL-match i research_notes
        if url and url in notes:
            return True

        # Fuzzy titel-match
        existing_title = _normalize(enc.get("title_en") or enc.get("encounter_id") or "")
        if title and existing_title:
            ratio = difflib.SequenceMatcher(None, title, existing_title).ratio()
            if ratio >= title_threshold:
                return True

    return False


# ---------------------------------------------------------------------------
# Steg 4: IMPORT — skapa uap.encounter i Odoo
# ---------------------------------------------------------------------------

def import_encounter(candidate: dict, classification: dict) -> Optional[int]:
    """
    Skapar en uap.encounter i uapdb med status=pending.
    Lagrar [MEDIA]-källa i research_notes + kopplar database_id om känd.
    """
    from classifiers.uap_classifier import queue_for_approval
    from clio_odoo import connect

    try:
        env = connect(
            url=ODOO_URL,
            db=ODOO_UAP_DB,
            user=ODOO_USER,
            password=ODOO_PASSWORD,
        )
    except Exception as e:
        logger.error(f"  Odoo-anslutning misslyckades: {e}")
        return None

    source_name = candidate.get("source_name", "")
    source_item = {
        "title":        candidate["title"],
        "url":          candidate["url"],
        "content":      candidate["content"][:2000],
        "published_at": candidate["payload"].get("published_at", ""),
        "source_name":  source_name,
    }

    try:
        odoo_id = queue_for_approval(env, classification, source_item)
    except Exception as e:
        logger.error(f"  queue_for_approval misslyckades: {e}")
        return None

    # Koppla database_id om källan är en känd uap.database
    if odoo_id and source_name:
        db_name = SOURCE_TO_DB_NAME.get(source_name)
        if db_name:
            db_id = _lookup_db_id(db_name)
            if db_id:
                try:
                    env["uap.encounter"].write([[odoo_id], {"database_id": db_id}])
                    logger.info(f"  database_id={db_id} kopplad till encounter {odoo_id}")
                except Exception as e:
                    logger.warning(f"  Kunde ej koppla database_id: {e}")

    return odoo_id


# ---------------------------------------------------------------------------
# Steg 5: REINDEX — uppdatera vigil_ufo med nya encounters
# ---------------------------------------------------------------------------

def reindex_encounters(dry_run: bool = False) -> bool:
    """Kör ingest_uap_tracking.py för att synka uapdb → vigil_ufo."""
    if dry_run:
        logger.info("[REINDEX] Dry-run — hoppar över re-indexering")
        return True

    ingest_script = _RAG_DIR / "ingest_uap_tracking.py"
    if not ingest_script.exists():
        logger.warning(f"[REINDEX] Skript saknas: {ingest_script}")
        return False

    logger.info("[REINDEX] Kör ingest_uap_tracking.py ...")
    result = subprocess.run(
        [sys.executable, str(ingest_script)],
        cwd=str(_RAG_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"[REINDEX] Fel:\n{result.stderr[-500:]}")
        return False

    for line in result.stdout.splitlines()[-5:]:
        logger.info(f"  {line}")
    return True


# ---------------------------------------------------------------------------
# Huvud-pipeline
# ---------------------------------------------------------------------------

def run(
    max_candidates: int = 100,
    score_threshold: float = 0.50,
    dry_run: bool = False,
) -> dict:
    banner = "DRY-RUN" if dry_run else "LIVE"
    logger.info(f"=== UAP Auto-Import [{banner}] ===")
    logger.info(f"  Score-tröskel : {score_threshold}")
    logger.info(f"  Max kandidater: {max_candidates}")

    state = load_state()
    processed = state.setdefault("processed", {})

    counts = {
        "searched":   0,
        "skipped_cache": 0,
        "classified": 0,
        "duplicate":  0,
        "imported":   0,
        "errors":     0,
    }

    # --- Steg 1: Sök ---
    candidates = search_candidates(
        score_threshold=score_threshold,
        top_per_query=max(20, max_candidates // len(SEARCH_QUERIES) + 1),
    )
    candidates = candidates[:max_candidates]
    counts["searched"] = len(candidates)

    if not candidates:
        logger.info("Inga kandidater hittade.")
        return counts

    # --- Ladda befintliga encounters för dedup ---
    logger.info("[DEDUP] Hämtar befintliga encounters från uapdb ...")
    try:
        existing = load_existing_encounters()
        logger.info(f"[DEDUP] {len(existing)} befintliga encounters laddade")
    except Exception as e:
        logger.error(f"[DEDUP] Kan inte nå Odoo: {e}")
        return counts

    new_imports = 0

    for i, cand in enumerate(candidates, 1):
        url   = cand.get("url", "")
        title = cand.get("title", "")[:60]
        key   = url_hash(url or title)

        logger.info(f"[{i}/{len(candidates)}] {title} (score={cand['score']:.2f})")

        # State-cache: hoppa över redan processerade
        if key in processed:
            prev = processed[key]
            logger.info(f"  → Cache: {prev['outcome']} ({prev['processed_at']})")
            counts["skipped_cache"] += 1
            continue

        # --- Steg 2: Klassificera ---
        try:
            clf = classify_candidate(cand)
        except Exception as e:
            logger.error(f"  Klassificeringsfel: {e}")
            counts["errors"] += 1
            processed[key] = {"outcome": "error", "processed_at": str(datetime.date.today())}
            continue

        counts["classified"] += 1
        conf     = clf.get("confidence", 0.0)
        enc_cls  = clf.get("encounter_class") or "N"
        is_cand  = clf.get("import_candidate", False)

        logger.info(
            f"  Klass={enc_cls} | Conf={conf:.0%} | "
            f"{'KANDIDAT' if is_cand else 'Ej kandidat'}"
        )

        if clf.get("error"):
            logger.warning(f"  Klassificeringsvarning: {clf['error']}")
            counts["errors"] += 1
            processed[key] = {"outcome": "error", "processed_at": str(datetime.date.today()), "confidence": conf}
            continue

        if not is_cand:
            processed[key] = {"outcome": "low_confidence", "processed_at": str(datetime.date.today()), "confidence": conf}
            continue

        # --- Steg 3: Dedup ---
        if is_duplicate(cand, existing):
            logger.info("  → Dubblett — hoppar över")
            counts["duplicate"] += 1
            processed[key] = {"outcome": "duplicate", "processed_at": str(datetime.date.today()), "confidence": conf}
            continue

        # --- Steg 4: Importera ---
        if dry_run:
            logger.info(f"  [DRY] Skulle importera: {cand['title'][:60]}")
            counts["imported"] += 1
            processed[key] = {"outcome": "dry_run", "processed_at": str(datetime.date.today()), "confidence": conf}
            continue

        odoo_id = import_encounter(cand, clf)
        if odoo_id:
            logger.info(f"  → Importerad till Odoo (ID: {odoo_id}, status=pending)")
            counts["imported"] += 1
            new_imports += 1
            processed[key] = {
                "outcome":      "imported",
                "odoo_id":      odoo_id,
                "processed_at": str(datetime.date.today()),
                "confidence":   conf,
            }
            # Lägg till i existing för dedup av resterande i denna körning
            existing.append({"title_en": cand["title"], "research_notes": url, "encounter_id": f"AUTO_{odoo_id}"})
        else:
            logger.error("  → Import misslyckades")
            counts["errors"] += 1
            processed[key] = {"outcome": "import_error", "processed_at": str(datetime.date.today()), "confidence": conf}

    # Spara state
    save_state(state)

    # --- Steg 5: Re-indexera om något importerades ---
    if new_imports > 0:
        reindex_encounters(dry_run=dry_run)
    else:
        logger.info("[REINDEX] Inga nya encounters — hoppar över re-indexering")

    logger.info(
        f"\n=== Klar ===\n"
        f"  Sökträffar    : {counts['searched']}\n"
        f"  Från cache    : {counts['skipped_cache']}\n"
        f"  Klassificerade: {counts['classified']}\n"
        f"  Dubbletter    : {counts['duplicate']}\n"
        f"  Importerade   : {counts['imported']}\n"
        f"  Fel           : {counts['errors']}"
    )
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="UAP Auto-Import: vigil_ufo → uapdb"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulera utan att skriva till Odoo",
    )
    parser.add_argument(
        "--max", type=int, default=100,
        metavar="N",
        help="Max antal kandidater att behandla (standard: 100)",
    )
    parser.add_argument(
        "--score-threshold", type=float, default=0.50,
        metavar="F",
        help="Minsta Qdrant-score för kandidater (standard: 0.50)",
    )
    parser.add_argument(
        "--clear-cache", action="store_true",
        help="Rensa state-cache och börja om från början",
    )
    args = parser.parse_args(argv)

    if args.clear_cache and STATE_FILE.exists():
        STATE_FILE.unlink()
        logger.info(f"State-cache rensad: {STATE_FILE}")

    run(
        max_candidates=args.max,
        score_threshold=args.score_threshold,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
