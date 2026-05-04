"""text_extractor.py — Wrapper mot clio-vigil/text_extractor.py."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_VIGIL_PATH = Path(__file__).parent.parent / "clio-vigil"
if _VIGIL_PATH.exists():
    sys.path.insert(0, str(_VIGIL_PATH))


def extract(url: str, item_id: int = 0, source_name: str = "", date: str = "",
            local_pdf: Path | None = None) -> dict | None:
    """
    Hämta fulltext från URL eller lokal PDF.
    Delegerar till clio-vigil/text_extractor.py om tillgänglig.
    Returnerar dict med transcript_path, source_type, word_count, title — eller None.
    """
    try:
        import text_extractor as _vigil_extractor
        return _vigil_extractor.extract(
            url=url,
            item_id=item_id,
            source_name=source_name,
            date=date,
            local_pdf=local_pdf,
        )
    except ImportError:
        logger.warning("clio-vigil/text_extractor.py ej tillgänglig — försöker direkt extraktion")

    return _fallback_extract(url)


def _fallback_extract(url: str) -> dict | None:
    """Minimalt fallback med trafilatura om clio-vigil saknas."""
    if not url:
        return None
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded)
        if not text:
            return None
        return {
            "transcript_path": None,
            "source_type": "web",
            "word_count": len(text.split()),
            "title": None,
            "text": text,
        }
    except Exception as e:
        logger.debug("Fallback extraktion misslyckades för %s: %s", url, e)
        return None
