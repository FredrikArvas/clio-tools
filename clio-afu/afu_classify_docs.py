#!/usr/bin/env python3
"""
afu_classify_docs.py — Klassificerar nedladdade AFU-dokument mot transmorf-taxonomin.

Flöde per fil:
  1. Textextraktion: PyMuPDF → om skannat PDF (gles text) → Tesseract OCR
  2. Ollama qwen2.5:3b → transmorf-klassificering
  3. Resume-safe JSONL-checkpoint keyed på relativ sökväg
  4. is_case_report=True → uap.encounter skapas i Odoo (status=pending)
  5. Uppdaterar clio.media.article.body om det var SENTINEL

Kör från ~/19.0/clio-tools/clio-afu/ på servern
Usage:
    python3 afu_classify_docs.py [--max N] [--dir TEXT] [--dry-run] [--model MODEL]
Systemberoenden (engångsinstallation på servern):
    sudo apt install tesseract-ocr tesseract-ocr-swe tesseract-ocr-eng poppler-utils
Pythonberoenden:
    pip install pytesseract pdf2image pymupdf python-docx striprtf python-dotenv requests
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import urllib.parse
import xmlrpc.client
from datetime import datetime, date, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ─── Konfiguration ────────────────────────────────────────────────────────────

_here = Path(__file__).parent
load_dotenv(_here.parent / ".env", override=True)

DOWNLOADS_DIR = _here / "data" / "downloads"
OUTPUT_FILE   = _here / "data" / "afu_docs_classified.jsonl"

OLLAMA_URL     = "http://localhost:11434/api/generate"
MODEL          = "qwen2.5:3b"
OLLAMA_TIMEOUT = 180

ODOO_URL  = os.getenv("VIGIL_ODOO_URL", "http://localhost:8069")
ODOO_DB   = os.getenv("VIGIL_ODOO_DB", "uap")
ODOO_USER = os.getenv("VIGIL_ODOO_USER", "")
ODOO_PWD  = os.getenv("VIGIL_ODOO_PASSWORD", "")

AFU_FILES_URL = "https://files.afu.se/Downloads/"

# Prioritetsordning: processas först, resten täcks av DOWNLOADS_DIR-catch
PRIORITY_DIRS = [
    "UFO-reports",
    "Databases/Archives/AFU/PhenCode",
    "Topics/0 - Cases",
    "Documents/USA - AARO",
    "Documents/USA - Congress",
    "Documents/USA - CIA/Stargate",
]

MAX_TEXT_CHARS     = 4000
SNIPPET_LEN        = 500
MIN_CHARS_PER_PAGE = 50    # under detta antas skannat PDF → OCR-försök
MAX_OCR_PAGES      = 20    # begränsa minnestrycket för stora PDF:er
SENTINEL_BODY      = " "   # markör från extract_afu_documents_text.py

SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".rtf", ".txt"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Transmorf-systemprompt (identisk med afu_enrich.py) ─────────────────────

SYSTEM_PROMPT = """\
Du är en analytiker för UAP/UFO-forskning. Klassificera texter enligt transmorf-taxonomin.
Svara ALLTID med ett JSON-objekt och INGENTING annat — ingen inledning, ingen förklaring.

Definitioner:
- is_case_report: true om texten beskriver ett faktiskt observationstillfälle/möte med UAP/fenomen
- craft_class: Skywatcher-klass (I=Tetra II=Tic-Tac III=Blob IV=Beam V=Manta-Ray VI=Bright-Star
  VII=Jellyfish VIII=Hornet IX=Egg X=Teardrop) eller "Unknown" eller null
- entity_type: Nordic | TallGray | ShortGray | LongGray | Reptilian | Mantid | Hybrid | Energy | Unknown | null
- eth_origin: 0-5
    0 = förklarat/mänskligt ursprung
    1 = troligen mänskligt, men oklart
    2 = okänt ursprung
    3 = stark icke-mänsklig indikation — KRÄVER fysisk evidens ELLER radar ELLER flera oberoende vittnen
    4 = starkt icke-mänskligt med officiell korroboration (militär/myndighet erkänt)
    5 = bekräftat icke-mänskligt av officiella declassificerade dokument
- intelligence_indicator: 0-3
    0 = inga tecken på intelligens
    1 = möjlig reaktiv/avsiktlig rörelse
    2 = tydlig intelligens
    3 = direkt kontakt eller kommunikation
- discourse_level: 1-5
    1 = fringe/spekulativt
    2 = rapporterat men ej dokumenterat
    3 = dokumenterat, utredning gjord, ej officiellt bekräftat
    4 = officiellt erkänt/undersökt av myndighet
    5 = bekräftat/declassifierat av officiell källa
- suppression_indicator: true om texten aktivt tonar ned ETH-implikationer för ett fall som matchar eth>=3
- suppression_note: kort notering (max 80 tecken) om varför suppression=true, annars null
- case_date: datum för händelsen (ISO 8601 eller YYYY-MM), ej publikationsdatum, null om okänt
- location: land/region om nämnt, null annars
- summary_sv: 1 mening på svenska som sammanfattar vad dokumentet handlar om
"""

CLASSIFY_PROMPT = """\
Klassificera följande dokument från AFU:s arkiv.

FILNAMN: {filename}
KÄLLA: {source_dir}

TEXT (max {max_chars} tecken):
{text}

Returnera exakt detta JSON (inga extra fält):
{{
  "is_case_report": false,
  "craft_class": null,
  "entity_type": null,
  "eth_origin": 0,
  "intelligence_indicator": 0,
  "discourse_level": 1,
  "suppression_indicator": false,
  "suppression_note": null,
  "case_date": null,
  "location": null,
  "summary_sv": ""
}}"""


# ─── Odoo ─────────────────────────────────────────────────────────────────────

def odoo_connect():
    """Returnerar kw-callable eller None vid fel."""
    if not all([ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PWD]):
        logger.warning("VIGIL_ODOO_* env vars saknas — Odoo-skrivning inaktiverad")
        return None
    try:
        common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
        uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PWD, {})
        if not uid:
            logger.error("Odoo-autentisering misslyckades — encounter-skapande inaktiverat")
            return None
        M = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
        def kw(model, method, args, kwargs=None):
            return M.execute_kw(ODOO_DB, uid, ODOO_PWD, model, method, args, kwargs or {})
        logger.info(f"Odoo ansluten: {ODOO_URL} db={ODOO_DB}")
        return kw
    except Exception as e:
        logger.error(f"Odoo-anslutning misslyckades: {e}")
        return None


def _filepath_to_url(filepath: str) -> str:
    parts = Path(filepath).parts
    encoded = "/".join(urllib.parse.quote(p, safe="") for p in parts)
    return AFU_FILES_URL + encoded


def find_article(kw, filepath: str) -> dict | None:
    """Söker clio.media.article via AFU-URL konstruerad från filsökvägen."""
    url = _filepath_to_url(filepath)
    rows = kw("clio.media.article", "search_read",
              [[["url", "=", url]]],
              {"fields": ["id", "body"], "limit": 1})
    return rows[0] if rows else None


def update_article_body(kw, article_id: int, text: str) -> None:
    snippet = text[:SNIPPET_LEN]
    kw("clio.media.article", "write",
       [[article_id], {"body": text, "body_snippet": snippet}])


def _normalize_selection_int(val, valid_range: range) -> str | None:
    try:
        v = int(val)
        return str(v) if v in valid_range else None
    except (TypeError, ValueError):
        return None


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
    # Redan ett giltigt romerskt tal-nyckel?
    if s in {"I","II","III","IV","V","VI","VII","VIII","IX","X","unknown"}:
        return s
    return None


def _build_encounter_vals(filepath: str, filename: str, source_dir: str,
                          cls: dict, article_id: int | None) -> dict:
    year = date.today().year
    path_hash = abs(hash(filepath)) % 9999
    auto_id = f"AFU_{year}_{path_hash:04d}"

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
            f"[AUTO] Klassificerat {date.today()} av afu_classify_docs.py\n"
            f"[ETH] eth_origin={cls.get('eth_origin')} | discourse={cls.get('discourse_level')}"
        ),
        "is_case_report":         True,
        "eth_origin":             _normalize_selection_int(cls.get("eth_origin"), range(6)) or False,
        "craft_class":            _normalize_craft_class(cls.get("craft_class")) or False,
        "entity_type":            (entity_raw if entity_raw in valid_entities else False),
        "intelligence_indicator": _normalize_selection_int(cls.get("intelligence_indicator"), range(4)) or False,
        "discourse_level":        _normalize_selection_int(cls.get("discourse_level"), range(1, 6)) or False,
        "suppression_indicator":  bool(cls.get("suppression_indicator", False)),
        "suppression_note":       (cls.get("suppression_note") or False),
        "afu_article_id":         article_id or 0,
        "afu_doc_path":           filepath[:500],
        "status":                 "pending",
    }


def create_encounter(kw, filepath: str, filename: str, source_dir: str,
                     cls: dict, article_id: int | None) -> int | None:
    """Skapar uap.encounter om det inte redan finns för detta dokument."""
    existing = kw("uap.encounter", "search",
                  [[["afu_doc_path", "=", filepath]]], {"limit": 1})
    if existing:
        logger.info(f"  Encounter finns redan för {filename} (id={existing[0]})")
        return existing[0]
    vals = _build_encounter_vals(filepath, filename, source_dir, cls, article_id)
    try:
        enc_id = kw("uap.encounter", "create", [vals])
        logger.info(f"  → uap.encounter skapad: id={enc_id} [{vals['encounter_id']}]")
        return enc_id
    except Exception as e:
        logger.error(f"  Odoo encounter-skapande misslyckades för {filename}: {e}")
        return None


# ─── Textextraktion ────────────────────────────────────────────────────────────

def _extract_pdf_pymupdf(path: Path) -> tuple[str, int]:
    """Returnerar (text, page_count)."""
    import fitz
    doc = fitz.open(str(path))
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(pages), len(pages)


def _ocr_pdf_tesseract(path: Path) -> str | None:
    """OCR via Tesseract. Returnerar None om verktygen saknas eller misslyckas."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        logger.warning("pdf2image/pytesseract saknas — kör: pip install pdf2image pytesseract")
        return None
    try:
        images = convert_from_path(
            str(path), dpi=200, last_page=MAX_OCR_PAGES, thread_count=2
        )
        return "\n".join(
            pytesseract.image_to_string(img, lang="swe+eng") for img in images
        )
    except Exception as e:
        logger.warning(f"OCR misslyckades för {path.name}: {e}")
        return None


def _extract_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_rtf(path: Path) -> str:
    from striprtf.striprtf import rtf_to_text
    return rtf_to_text(path.read_bytes().decode("utf-8", errors="replace"))


def _extract_doc_antiword(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["antiword", str(path)], capture_output=True, text=True, timeout=30
        )
        return result.stdout if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def clean_text(raw: str) -> str:
    text = re.sub(r"[ \t]+", " ", raw)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", text)   # ta bort rena sidnummer
    return text.strip()


def extract_text_full(path: Path) -> str | None:
    """
    Extraherar text ur filen. För skannade PDF:er (gles PyMuPDF-text)
    försöker vi med Tesseract OCR.
    Returnerar None om ingen text kan utvinnas eller formatet är okänt.
    """
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            raw, page_count = _extract_pdf_pymupdf(path)
            # Skannat PDF-test: snitt under MIN_CHARS_PER_PAGE → OCR-försök
            if page_count > 0 and len(raw.strip()) < MIN_CHARS_PER_PAGE * page_count:
                ocr_raw = _ocr_pdf_tesseract(path)
                if ocr_raw and len(ocr_raw.strip()) > len(raw.strip()):
                    raw = ocr_raw
            text = clean_text(raw)
        elif ext == ".docx":
            text = clean_text(_extract_docx(path))
        elif ext == ".rtf":
            text = clean_text(_extract_rtf(path))
        elif ext == ".doc":
            raw = _extract_doc_antiword(path)
            text = clean_text(raw) if raw else ""
        elif ext == ".txt":
            text = clean_text(path.read_bytes().decode("utf-8", errors="replace"))
        else:
            return None
    except Exception as e:
        raise RuntimeError(f"Textextraktion misslyckades: {e}") from e

    return text if text else None


# ─── Ollama-klassificering ────────────────────────────────────────────────────

def classify_transmorf(text: str, filename: str, source_dir: str, model: str) -> dict:
    prompt = CLASSIFY_PROMPT.format(
        filename=filename,
        source_dir=source_dir,
        max_chars=MAX_TEXT_CHARS,
        text=text[:MAX_TEXT_CHARS],
    )
    payload = {
        "model":   model,
        "system":  SYSTEM_PROMPT,
        "prompt":  prompt,
        "stream":  False,
        "format":  "json",
        "options": {"temperature": 0.1},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json().get("response", "{}")
    return json.loads(raw)


# ─── Filsamling ───────────────────────────────────────────────────────────────

def collect_files(dir_filter: str | None = None) -> list[tuple[Path, str, str]]:
    """
    Returnerar lista av (path, relative_filepath, source_dir) i prioritetsordning.
    relative_filepath är relativ till DOWNLOADS_DIR (Linux-sökvägar).
    Prioritetskataloger processas alltid före övriga.
    """
    result: list[tuple[Path, str, str]] = []
    seen: set[str] = set()

    def _add_dir(walk_root: Path) -> None:
        if not walk_root.exists():
            return
        for path in sorted(walk_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            rel = path.relative_to(DOWNLOADS_DIR)
            fp = rel.as_posix()      # alltid forward slashes, oavsett OS
            if fp in seen:
                continue
            seen.add(fp)
            source_dir = rel.parts[0] if rel.parts else ""
            result.append((path, fp, source_dir))

    if dir_filter:
        _add_dir(DOWNLOADS_DIR / dir_filter)
    else:
        for pdir in PRIORITY_DIRS:
            _add_dir(DOWNLOADS_DIR / pdir)
        _add_dir(DOWNLOADS_DIR)   # täcker allt utanför prioritetskatalogerna

    return result


# ─── Checkpoint ───────────────────────────────────────────────────────────────

def load_done_paths(output_file: Path) -> set[str]:
    done: set[str] = set()
    if not output_file.exists():
        return done
    with open(output_file, encoding="utf-8") as f:
        for line in f:
            try:
                done.add(json.loads(line)["filepath"])
            except Exception:
                pass
    return done


# ─── Hjälpfunktioner ──────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_record(out, record: dict) -> None:
    out.write(json.dumps(record, ensure_ascii=False) + "\n")
    out.flush()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Transmorf-klassificering av nedladdade AFU-dokument via Ollama"
    )
    parser.add_argument("--max",     type=int,   default=0,
                        help="Max antal filer att processa (0 = alla)")
    parser.add_argument("--dir",     type=str,   default=None,
                        help="Kör bara en subdirectory (t.ex. 'UFO-reports')")
    parser.add_argument("--model",   type=str,   default=MODEL,
                        help=f"Ollama-modell (default: {MODEL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Klassificera men skriv inte till Odoo")
    args = parser.parse_args()

    if not DOWNLOADS_DIR.exists():
        sys.exit(f"FEL: {DOWNLOADS_DIR} saknas — kör på servern")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    done_paths = load_done_paths(OUTPUT_FILE)
    logger.info(f"Checkpoint: {len(done_paths)} filer redan klara")

    files = collect_files(args.dir)
    todo  = [(p, fp, sd) for p, fp, sd in files if fp not in done_paths]
    if args.max:
        todo = todo[: args.max]
    logger.info(f"Att klassificera: {len(todo)} filer | modell={args.model} | dry-run={args.dry_run}")

    kw = None
    if not args.dry_run:
        kw = odoo_connect()

    stats = {
        "ok":               0,
        "case_report":      0,
        "encounter_created": 0,
        "no_text":          0,
        "error":            0,
    }

    with open(OUTPUT_FILE, "a", encoding="utf-8") as out:
        for i, (path, filepath, source_dir) in enumerate(todo, 1):
            filename = path.name
            label = f"[{i}/{len(todo)}] {source_dir}/{filename[:50]}"

            # 1. Textextraktion
            try:
                text = extract_text_full(path)
            except RuntimeError as e:
                logger.warning(f"{label} — {e}")
                _write_record(out, {
                    "filepath": filepath, "filename": filename,
                    "source_dir": source_dir, "error": str(e),
                    "enriched_at": _now(),
                })
                stats["error"] += 1
                continue

            if not text:
                logger.info(f"{label} — ingen text kunde utvinnas")
                _write_record(out, {
                    "filepath": filepath, "filename": filename,
                    "source_dir": source_dir, "text_chars": 0,
                    "is_case_report": False, "enriched_at": _now(),
                })
                stats["no_text"] += 1
                continue

            # 2. Ollama-klassificering
            try:
                cls = classify_transmorf(text, filename, source_dir, args.model)
            except Exception as e:
                logger.warning(f"{label} — Ollama-fel: {e}")
                _write_record(out, {
                    "filepath": filepath, "filename": filename,
                    "source_dir": source_dir, "error": str(e),
                    "enriched_at": _now(),
                })
                stats["error"] += 1
                continue

            is_case = bool(cls.get("is_case_report", False))
            eth     = cls.get("eth_origin", 0)
            sup     = cls.get("suppression_indicator", False)
            if is_case or int(eth or 0) >= 2 or sup:
                logger.info(f"{label} ★ case={is_case} eth={eth} suppress={sup}")

            # 3. Uppdatera clio.media.article om body var SENTINEL
            article_id = None
            if kw:
                try:
                    article = find_article(kw, filepath)
                    if article:
                        article_id = article["id"]
                        body = article.get("body")
                        if body is False or (isinstance(body, str) and body.strip() == ""):
                            update_article_body(kw, article_id, text)
                except Exception as e:
                    logger.warning(f"{label} — article-uppdatering misslyckades: {e}")

            # 4. Skapa uap.encounter vid fallrapport
            encounter_odoo_id = None
            if is_case and kw:
                encounter_odoo_id = create_encounter(
                    kw, filepath, filename, source_dir, cls, article_id
                )
                if encounter_odoo_id:
                    stats["encounter_created"] += 1

            _write_record(out, {
                "filepath":          filepath,
                "source_dir":        source_dir,
                "filename":          filename,
                "text_chars":        len(text),
                "encounter_odoo_id": encounter_odoo_id,
                "enriched_at":       _now(),
                **cls,
            })
            stats["ok"] += 1
            if is_case:
                stats["case_report"] += 1

    logger.info(
        f"Klart! OK={stats['ok']} | Fallrapporter={stats['case_report']} | "
        f"Encounter skapade={stats['encounter_created']} | "
        f"Ingen text={stats['no_text']} | Fel={stats['error']}"
    )


if __name__ == "__main__":
    main()
