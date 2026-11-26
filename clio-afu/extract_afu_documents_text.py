#!/usr/bin/env python3
"""
extract_afu_documents_text.py — Extraherar text ur nedladdade AFU-dokument → clio.media.article.body

Hämtar poster med data_source LIKE 'afu_%' och body IS NULL,
konstruerar lokal filsökväg från URL, extraherar text via PyMuPDF/python-docx/striprtf
och uppdaterar body + body_snippet på posten.

Resumable: poster med body != False hoppas automatiskt över.

Kör från ~/19.0/clio-tools/clio-afu/ på servern
Usage:
    python3 extract_afu_documents_text.py [--max N] [--batch-size N] [--dry-run]
Beroenden:
    pip install pymupdf python-docx striprtf python-dotenv
"""

import argparse
import os
import re
import sys
import urllib.parse
import xmlrpc.client
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("VIGIL_ODOO_URL", "http://localhost:8069")
DB   = os.getenv("VIGIL_ODOO_DB", "uap")
USER = os.getenv("VIGIL_ODOO_USER", "")
PWD  = os.getenv("VIGIL_ODOO_PASSWORD", "")

DOWNLOAD_BASE = Path(__file__).parent / "data" / "downloads"
AFU_FILES_URL = "https://files.afu.se/Downloads/"
SNIPPET_LEN   = 500
BATCH_SIZE    = 50


def odoo_connect():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, PWD, {})
    if not uid:
        sys.exit("Odoo-autentisering misslyckades")
    M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    def kw(model, method, args, kwargs=None):
        return M.execute_kw(DB, uid, PWD, model, method, args, kwargs or {})
    return kw


def url_to_local_path(url: str) -> Path | None:
    if not url.startswith(AFU_FILES_URL):
        return None
    rel_encoded = url[len(AFU_FILES_URL):]
    parts = rel_encoded.split("/")
    decoded = [urllib.parse.unquote(p) for p in parts]
    return DOWNLOAD_BASE / Path(*decoded)


def extract_pdf(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n".join(pages)
    except Exception as exc:
        raise RuntimeError(f"PDF-extraktion misslyckades: {exc}") from exc


def extract_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        raise RuntimeError(f"DOCX-extraktion misslyckades: {exc}") from exc


def extract_rtf(path: Path) -> str:
    try:
        from striprtf.striprtf import rtf_to_text
        content = path.read_bytes().decode("utf-8", errors="replace")
        return rtf_to_text(content)
    except Exception as exc:
        raise RuntimeError(f"RTF-extraktion misslyckades: {exc}") from exc


def extract_txt(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def extract_text(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext in (".docx",):
        return extract_docx(path)
    if ext == ".rtf":
        return extract_rtf(path)
    if ext == ".txt":
        return extract_txt(path)
    return None


def clean_text(raw: str) -> str:
    text = re.sub(r"[ \t]+", " ", raw)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_pending(kw, batch_size: int, offset: int) -> list[dict]:
    return kw(
        "clio.media.article", "search_read",
        [[
            ["data_source", "like", "afu_"],
            ["body", "=", False],
        ]],
        {"fields": ["id", "url", "title"], "limit": batch_size, "offset": offset},
    )


SENTINEL = " "  # body-checkpoint för filer utan textextraktion


def process_record(record: dict) -> dict:
    """Returnerar alltid en dict: body satt till SENTINEL om text ej kan extraheras."""
    path = url_to_local_path(record["url"])
    if path is None or not path.exists():
        return {"body": SENTINEL}
    try:
        raw = extract_text(path)
    except RuntimeError:
        return {"body": SENTINEL}
    if raw is None:
        return {"body": SENTINEL}
    text = clean_text(raw)
    if not text:
        return {"body": SENTINEL}
    snippet = text[:SNIPPET_LEN]
    title_from_text = None
    first_line = text.split("\n", 1)[0].strip()
    if first_line and len(first_line) < 200 and len(first_line) > 5:
        title_from_text = first_line
    return {
        "body":         text,
        "body_snippet": snippet,
        "title":        title_from_text or record["title"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max",        type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--dry-run",    action="store_true")
    args = parser.parse_args()

    kw = odoo_connect()
    print(f"Ansluten till {URL} db={DB}")

    total_extracted = total_sentinel = total_errors = 0

    while True:
        batch = fetch_pending(kw, args.batch_size, 0)
        if not batch:
            break
        for rec in batch:
            vals = process_record(rec)
            is_sentinel = vals.get("body") == SENTINEL
            if args.dry_run:
                if not is_sentinel:
                    print(f"  [DRY] id={rec['id']} title={vals.get('title','')[:60]}")
                total_extracted += (0 if is_sentinel else 1)
                total_sentinel  += (1 if is_sentinel else 0)
                continue
            try:
                kw("clio.media.article", "write", [[rec["id"]], vals])
                if is_sentinel:
                    total_sentinel += 1
                else:
                    total_extracted += 1
            except Exception as exc:
                total_errors += 1
                print(f"  FEL id={rec['id']}: {exc}")

        done = total_extracted + total_sentinel + total_errors
        print(f"  [{done}] +{total_extracted} extraherade, {total_sentinel} sentinel, {total_errors} fel")

        if args.max and done >= args.max:
            break

        if len(batch) < args.batch_size:
            break

    print(f"\nKlart! Extraherade: {total_extracted} | Sentinel: {total_sentinel} | Fel: {total_errors}")


if __name__ == "__main__":
    main()
