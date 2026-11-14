"""
contact.py
Kontaktadressen som Unpaywall och Crossref kräver i anropen.

Beslut U1/U3 (Fredrik, 2026-11-14): adressen får skickas till Unpaywall och Crossref.
Den läses ur miljövariabeln och får aldrig hårdkodas, loggas eller sparas i körkatalogen.
Allt som kan innehålla en anrops-URL (felmeddelanden, loggrader) ska gå genom `redact`.

Environment:
    CLIO_CONTACT_EMAIL  – kontaktadress; saknas den hoppas Unpaywall och Crossrefs polite pool över
"""

from __future__ import annotations

import os
from urllib.parse import quote, quote_plus

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "1.0.0"

ENV_VAR = "CLIO_CONTACT_EMAIL"
MASK = "<kontaktadress>"


def contact_email() -> str | None:
    """Returnera kontaktadressen ur miljön, eller None om den inte är satt."""
    value = (os.environ.get(ENV_VAR) or "").strip()
    return value or None


def redact(text) -> str:
    """Ersätt kontaktadressen (även URL-kodad) med en mask. Tål vilket värde som helst."""
    text = str(text)
    email = contact_email()
    if not email:
        return text
    for variant in {email, quote(email, safe=""), quote_plus(email), email.replace("@", "%40")}:
        text = text.replace(variant, MASK)
    lowered = text.lower()
    needle = email.lower()
    while needle in lowered:
        start = lowered.index(needle)
        text = text[:start] + MASK + text[start + len(needle):]
        lowered = text.lower()
    return text
