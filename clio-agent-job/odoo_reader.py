"""
odoo_reader.py
Läser clio-agent-job-profiler från Odoo (clio.job.profile + res.partner).
Returnerar samma dict-struktur som yaml_loader så run.py inte behöver ändras.

Kräver: clio_odoo/connection.py + ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD i .env
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
for _p in [str(_ROOT), str(_ROOT / "clio_odoo")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _text_to_list(value: str) -> list[str]:
    """Radbruten Odoo-text → lista (omvändning av _lines_to_text i migrationen)."""
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


def load_profiles(partner_email: str | None = None) -> list[dict]:
    """
    Hämtar aktiva clio.job.profile-poster från Odoo.

    Args:
        partner_email: Filtrera på en specifik e-postadress (för --profile-flaggan).

    Returns:
        Lista av profil-dicts med samma nycklar som YAML-profilerna.
    """
    from clio_odoo import connect

    try:
        env = connect()
    except Exception as exc:
        _logger.error("Kunde inte ansluta till Odoo: %s", exc)
        raise

    Profile = env["clio.job.profile"]
    Partner = env["res.partner"]

    # Bygg sökfilter
    domain = [("active", "=", True)]

    profile_fields = [
        "id", "partner_id", "report_email",
        "role", "seniority", "geography", "hybrid_ok",
        "background", "education", "target_roles", "signal_keywords",
    ]
    raw_profiles = Profile.search_read(domain, profile_fields)

    if not raw_profiles:
        _logger.warning("Inga aktiva profiler hittades i Odoo.")
        return []

    results = []
    for p in raw_profiles:
        # Hämta partner-info (namn, e-post)
        partner_id = p.get("partner_id")
        if isinstance(partner_id, (list, tuple)):
            pid = partner_id[0]
        else:
            pid = partner_id

        partner_rows = Partner.search_read(
            [("id", "=", pid)], ["name", "email"]
        )
        partner = partner_rows[0] if partner_rows else {}

        name  = partner.get("name", "")
        email = p.get("report_email") or partner.get("email", "")

        # Filtrera på e-post om --profile angavs
        if partner_email and email.lower() != partner_email.lower():
            continue

        profile = {
            "name":            name,
            "email":           email,
            "language":        "sv",
            "role":            p.get("role", "") or "",
            "seniority":       p.get("seniority", "") or "",
            "geography":       p.get("geography", "") or "",
            "hybrid_ok":       bool(p.get("hybrid_ok", True)),
            "background":      _text_to_list(p.get("background", "")),
            "education":       _text_to_list(p.get("education", "")),
            "target_roles":    _text_to_list(p.get("target_roles", "")),
            "signal_keywords": _text_to_list(p.get("signal_keywords", "")),
            # Metadata för odoo_writer
            "_odoo_profile_id": p["id"],
            "_odoo_partner_id": pid,
        }
        results.append(profile)
        _logger.debug("Profil laddad: %s (%s)", name, email)

    _logger.info("Laddade %d profil(er) från Odoo.", len(results))
    return results


def load_profile_by_email(email: str) -> dict | None:
    """Returnerar en enskild profil eller None om den inte finns."""
    profiles = load_profiles(partner_email=email)
    return profiles[0] if profiles else None
