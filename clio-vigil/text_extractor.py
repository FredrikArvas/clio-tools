"""
clio-vigil — text_extractor.py
================================
Extraherar text från webb-sidor och PDF:er för import i vigil-pipeline.

Stöder:
  - PDF via URL eller lokal fil  → pymupdf (fitz)
  - Webb-artikel via URL         → trafilatura

Output: .txt-fil sparad i data/transcripts/ med samma namnschema
som transcriber.py använder för audio.

Returnerar dict kompatibelt med vigil_items-schemat.
"""

import logging
import re
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR        = Path(__file__).parent / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"


# ---------------------------------------------------------------------------
# Filnamn (samma logik som transcriber._make_slug)
# ---------------------------------------------------------------------------

def _make_slug(text: str, max_len: int = 20) -> str:
    text = text.lower()
    text = text.replace("å", "a").replace("ä", "a").replace("ö", "o")
    text = text.replace("é", "e").replace("ü", "u").replace("ñ", "n")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:max_len].rstrip("-")


def _text_filename(item_id: int, source: str, date: str = "") -> str:
    slug  = _make_slug(source or "import")
    date  = (date or "")[:10].replace("-", "") or "nodatum"
    return f"{slug}_{item_id}_{date}.txt"


# ---------------------------------------------------------------------------
# URL-typ-detektering
# ---------------------------------------------------------------------------

def _detect_type(url: str) -> str:
    """Returnerar 'pdf' eller 'html' baserat på URL och Content-Type."""
    url_lower = url.lower()
    if url_lower.endswith(".pdf") or "/pdf/" in url_lower:
        return "pdf"
    # HEAD-request för att kolla Content-Type
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "pdf" in ct.lower():
                return "pdf"
    except Exception:
        pass
    return "html"


# ---------------------------------------------------------------------------
# PDF-extraktion via pymupdf
# ---------------------------------------------------------------------------

def _extract_pdf_from_url(url: str) -> Optional[str]:
    """Laddar ned PDF från URL och extraherar text via pymupdf."""
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError("pymupdf saknas — kör: pip install pymupdf")

    logger.info(f"Laddar ned PDF: {url[:70]}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            pdf_bytes = resp.read()
    except Exception as e:
        logger.error(f"Kunde inte ladda ned PDF: {e}")
        return None

    try:
        doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc, 1):
            text = page.get_text("text").strip()
            if text:
                pages.append(f"[Sida {i}]\n{text}")
        doc.close()
        full_text = "\n\n".join(pages)
        logger.info(f"PDF extraherad: {len(doc)} sidor, {len(full_text):,} tecken")
        return full_text
    except Exception as e:
        logger.error(f"PDF-extraktion misslyckades: {e}")
        return None


def _extract_pdf_from_file(path: Path) -> Optional[str]:
    """Extraherar text från lokal PDF-fil via pymupdf."""
    try:
        import fitz
    except ImportError:
        raise ImportError("pymupdf saknas — kör: pip install pymupdf")

    try:
        doc   = fitz.open(str(path))
        pages = []
        for i, page in enumerate(doc, 1):
            text = page.get_text("text").strip()
            if text:
                pages.append(f"[Sida {i}]\n{text}")
        doc.close()
        return "\n\n".join(pages)
    except Exception as e:
        logger.error(f"Lokal PDF-extraktion misslyckades: {e}")
        return None


# ---------------------------------------------------------------------------
# Webb-extraktion via trafilatura
# ---------------------------------------------------------------------------

def _extract_html(url: str) -> Optional[str]:
    """Extraherar artikeltext från webb-URL via trafilatura."""
    try:
        import trafilatura
    except ImportError:
        raise ImportError("trafilatura saknas — kör: pip install trafilatura")

    logger.info(f"Hämtar webb-sida: {url[:70]}")
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            logger.error("Kunde inte hämta URL")
            return None

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        if not text:
            logger.error("trafilatura extraherade ingen text")
            return None

        # Extrahera titel om möjligt
        meta = trafilatura.extract_metadata(downloaded)
        title = meta.title if meta and meta.title else ""

        result = f"{title}\n\n{text}" if title else text
        logger.info(f"Webb-text extraherad: {len(result):,} tecken")
        return result

    except Exception as e:
        logger.error(f"Webb-extraktion misslyckades: {e}")
        return None


# ---------------------------------------------------------------------------
# Huvud-extraktionsfunktion
# ---------------------------------------------------------------------------

def extract(url: str, item_id: int, source_name: str = "",
            date: str = "", local_pdf: Path = None) -> Optional[dict]:
    """
    Extraherar text från URL (PDF eller HTML) och sparar till disk.

    Returnerar dict med:
      transcript_path: str  — sökväg till sparad .txt-fil
      source_type:     str  — 'pdf' eller 'web'
      word_count:      int  — antal ord
      title:           str  — extraherad rubrik om tillgänglig
    """
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # Välj extraktionsmetod
    if local_pdf:
        source_type = "pdf"
        text = _extract_pdf_from_file(local_pdf)
    else:
        source_type_raw = _detect_type(url)
        if source_type_raw == "pdf":
            source_type = "pdf"
            text = _extract_pdf_from_url(url)
        else:
            source_type = "web"
            text = _extract_html(url)

    if not text or not text.strip():
        logger.error(f"Ingen text extraherad från {url[:60]}")
        return None

    # Spara till disk
    filename = _text_filename(item_id, source_name or url[:30], date)
    out_path  = TRANSCRIPTS_DIR / filename
    out_path.write_text(text, encoding="utf-8")

    word_count = len(text.split())

    # Extrahera rubrik från första raden om möjligt
    first_line = text.split("\n")[0].strip()
    title = first_line if len(first_line) < 120 else ""

    logger.info(f"Text sparad: {filename} ({word_count:,} ord)")

    return {
        "transcript_path": str(out_path),
        "source_type":     source_type,
        "word_count":      word_count,
        "title":           title,
    }
