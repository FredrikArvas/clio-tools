"""
Läser afu_docs_classified.jsonl och skapar uap.encounter i Odoo
för alla poster med is_case_report=True som saknar encounter_odoo_id.

Kör:
    python afu_create_encounters.py [--dry-run] [--limit N]
"""

import argparse
import hashlib
import json
import logging
import sys
import xmlrpc.client
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CHECKPOINT = Path(__file__).parent / "data" / "afu_docs_classified.jsonl"


# ─── Odoo ─────────────────────────────────────────────────────────────────────

def odoo_connect():
    url  = os.environ["VIGIL_ODOO_URL"]
    db   = os.environ["VIGIL_ODOO_DB"]
    user = os.environ["VIGIL_ODOO_USER"]
    pw   = os.environ["VIGIL_ODOO_PASSWORD"]
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, pw, {})
    if not uid:
        raise RuntimeError("Odoo-autentisering misslyckades")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def kw(model, method, *a, **kw_):
        return models.execute_kw(db, uid, pw, model, method, *a, **kw_)

    logger.info(f"Odoo ansluten: {url} db={db}")
    return kw


# ─── Normalisering ─────────────────────────────────────────────────────────────

def _normalize_selection_int(val, valid_range: range) -> str | None:
    if val is None:
        return None
    try:
        i = int(str(val).strip())
        if i in valid_range:
            return str(i)
    except (ValueError, TypeError):
        pass
    return None


def to_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


_CRAFT_NAME_TO_KEY = {
    "tetra": "I", "tic-tac": "II", "tic tac": "II", "tictac": "II",
    "blob": "III", "beam": "IV", "manta-ray": "V", "manta ray": "V", "manta": "V",
    "bright-star": "VI", "bright star": "VI", "jellyfish": "VII",
    "hornet": "VIII", "egg": "IX", "teardrop": "X",
    "i": "I", "ii": "II", "iii": "III", "iv": "IV", "v": "V",
    "vi": "VI", "vii": "VII", "viii": "VIII", "ix": "IX", "x": "X",
}


def _normalize_craft_class(val) -> str | None:
    if not val or str(val).lower() in ("null", "none", ""):
        return None
    s = str(val).strip()
    mapped = _CRAFT_NAME_TO_KEY.get(s.lower())
    if mapped:
        return mapped
    if s == "Unknown":
        return "unknown"
    if s in {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "unknown"}:
        return s
    return None


def _filepath_to_url(filepath: str) -> str:
    base = "https://archive.org/details/"
    name = Path(filepath).stem
    return f"{base}{name}"


# ─── Encounter-byggare ────────────────────────────────────────────────────────

def _build_encounter_vals(filepath: str, filename: str, source_dir: str,
                          cls: dict, article_id: int | None) -> dict:
    path_hash = hashlib.sha1(filepath.encode("utf-8")).hexdigest()[:10]
    auto_id = f"AFU_{path_hash}"

    valid_entities = {
        "Nordic", "TallGray", "ShortGray", "LongGray",
        "Reptilian", "Mantid", "Hybrid", "Energy", "Unknown",
    }
    entity_raw = cls.get("entity_type")

    return {
        "encounter_id":           auto_id,
        "title_en":               filename[:255],
        "description_en":         (cls.get("summary_sv") or "")[:2000],
        "research_notes": (
            f"[SRC] {_filepath_to_url(filepath)}\n"
            f"[DIR] {source_dir}\n"
            f"[AUTO] Klassificerat {date.today()} av afu_create_encounters.py\n"
            f"[ETH] eth_origin={cls.get('eth_origin')} | discourse={cls.get('discourse_level')}"
        ),
        "is_case_report":         True,
        "eth_origin":             _normalize_selection_int(cls.get("eth_origin"), range(6)) or False,
        "craft_class":            _normalize_craft_class(cls.get("craft_class")) or False,
        "entity_type":            (entity_raw if entity_raw in valid_entities else False),
        "intelligence_indicator": _normalize_selection_int(cls.get("intelligence_indicator"), range(4)) or False,
        "discourse_level":        _normalize_selection_int(cls.get("discourse_level"), range(1, 6)) or False,
        "suppression_indicator":  to_bool(cls.get("suppression_indicator")),
        "suppression_note":       (cls.get("suppression_note") or False),
        "afu_article_id":         article_id or 0,
        "article_ids":            [(4, article_id)] if article_id else [],
        "afu_doc_path":           filepath[:500],
        "status":                 "pending",
    }


def create_encounter(kw, rec: dict, dry_run: bool) -> int | None:
    filepath   = rec["filepath"]
    filename   = rec.get("filename", Path(filepath).name)
    source_dir = rec.get("source_dir", "")
    article_id = rec.get("afu_article_id") or None

    vals = _build_encounter_vals(filepath, filename, source_dir, rec, article_id)
    if dry_run:
        logger.info(f"  [DRY] Skulle skapa: {vals['encounter_id']} — {filename[:60]}")
        return -1

    existing = kw("uap.encounter", "search",
                  [[["afu_doc_path", "=", filepath]]], {"limit": 1})
    if existing:
        logger.info(f"  Finns redan: {filename} (id={existing[0]})")
        return existing[0]

    try:
        enc_id = kw("uap.encounter", "create", [vals])
        logger.info(f"  → Skapad: id={enc_id} [{vals['encounter_id']}] {filename[:60]}")
        return enc_id
    except Exception as e:
        logger.error(f"  MISSLYCKADES {filename}: {e}")
        return None


# ─── Huvudlogik ───────────────────────────────────────────────────────────────

def load_case_reports(limit: int | None) -> list[dict]:
    cases = []
    if not CHECKPOINT.exists():
        logger.error(f"Checkpoint saknas: {CHECKPOINT}")
        return cases
    with open(CHECKPOINT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if to_bool(rec.get("is_case_report")) and not rec.get("encounter_odoo_id"):
                cases.append(rec)
            if limit and len(cases) >= limit:
                break
    return cases


def main():
    parser = argparse.ArgumentParser(description="Skapa uap.encounter från AFU-checkpoint")
    parser.add_argument("--dry-run", action="store_true", help="Simulera utan att skriva till Odoo")
    parser.add_argument("--limit",   type=int, default=None, help="Max antal encounters att skapa")
    args = parser.parse_args()

    cases = load_case_reports(args.limit)
    logger.info(f"Fallrapporter att processa: {len(cases)}")
    if not cases:
        logger.info("Inget att göra.")
        return

    kw = odoo_connect() if not args.dry_run else None
    if not args.dry_run and kw is None:
        sys.exit("Kunde inte ansluta till Odoo")

    created = skipped = failed = 0
    for i, rec in enumerate(cases, 1):
        logger.info(f"[{i}/{len(cases)}] {rec.get('source_dir','')}/{rec.get('filename','')[:50]}")
        result = create_encounter(kw, rec, dry_run=args.dry_run)
        if result is None:
            failed += 1
        elif result == -1:
            created += 1  # dry-run
        elif result > 0:
            # Kontrollera om det var ny eller befintlig
            if "Finns redan" in str(result):
                skipped += 1
            else:
                created += 1

    logger.info(f"Klart! Skapade={created} | Hoppade över={skipped} | Fel={failed}")


if __name__ == "__main__":
    main()
