"""
sources/parsers.py — Delade extraktionshelpers för dödsannonskällor

Lyfta från source_familjesidan.py i 0.2.0 så både RSS- och HTML-adaptrar
delar samma logik för att hitta födelseår, hemort och datum i annonser.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


def extract_birth_year(text: str) -> Optional[int]:
    """
    Försöker extrahera födelseår ur annonstext.
    Letar efter "född 1942", "f. 1942", "*1942", "1942-2026", samt fristående år.
    """
    if not text:
        return None
    patterns = [
        r"f(?:ödd|\.)\s*(\d{4})",
        r"\*\s*(\d{4})",
        r"(\d{4})\s*[-–]\s*\d{4}",
        r"\b(19[2-9]\d|20[0-1]\d)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            year = int(m.group(1))
            if 1900 <= year <= 2010:
                return year
    return None


def extract_location(text: str) -> Optional[str]:
    """
    Hemortsutvinning. Sprint 2 — för 0.2.0 returneras None.
    Matchningen får då falla tillbaka på namn + födelseår,
    vilket är medvetet enligt designprincipen.
    """
    return None


def parse_publication_date(value) -> str:
    """
    Tar antingen en feedparser-entry, en datetime eller en sträng
    och returnerar ett ISO-datum (YYYY-MM-DD). Faller tillbaka på
    dagens datum om inget kan tolkas.
    """
    # feedparser entry med published_parsed
    if hasattr(value, "published_parsed") and value.published_parsed:
        try:
            return datetime(*value.published_parsed[:6]).strftime("%Y-%m-%d")
        except Exception:
            pass
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str) and value:
        # Försök ISO-format först
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d %b %Y"):
            try:
                return datetime.strptime(value[: len(fmt) + 4], fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return datetime.now().strftime("%Y-%m-%d")


def clean_name(raw_title: str) -> str:
    """Tar bort vanliga prefix från en annonsrubrik så bara namnet kvarstår."""
    if not raw_title:
        return ""
    return re.sub(
        r"^(in memoriam|minnesruna|dödsannons|till minne av)[:\s]+",
        "",
        raw_title,
        flags=re.IGNORECASE,
    ).strip()
