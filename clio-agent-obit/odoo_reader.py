"""
odoo_reader.py
Läser bevakningslistan från Odoo (res.partner där clio_obit_watch=True).
Returnerar samma dict-struktur som _load_all_watchlists() i run.py
så att resten av koden inte behöver ändras.

Kräver: clio_odoo/connection.py + ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD i .env
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matcher import WatchlistEntry

_logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
for _p in [str(_ROOT), str(_ROOT / "clio_odoo")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _split_name(full_name: str) -> tuple[str, str]:
    """
    Delar upp "Förnamn Efternamn" → (fornamn, efternamn).
    Sista ordet = efternamn, resten = förnamn.
    "Göran Frisk"       → ("Göran", "Frisk")
    "Karl Gustav Berg"  → ("Karl Gustav", "Berg")
    """
    parts = (full_name or "").strip().split()
    if len(parts) == 0:
        return ("", "")
    if len(parts) == 1:
        return ("", parts[0])
    return (" ".join(parts[:-1]), parts[-1])


def load_watchlist_from_odoo(
    env,
    default_notify_email: str = "",
) -> dict[str, list] | None:
    """
    Hämtar aktiva bevakningsposter från Odoo.

    Args:
        env:                  OdooConnector (från odoo_writer.get_odoo_env())
        default_notify_email: E-post att använda om clio_obit_notify_email är tomt.
                              Typiskt notify.to från config.yaml.

    Returns:
        Dict {owner_email: [WatchlistEntry, ...]} — samma format som _load_all_watchlists().
        None om anslutning misslyckades.
    """
    if env is None:
        return None

    # Import här för att undvika cirkulärt beroende vid import av modulen
    sys.path.insert(0, str(Path(__file__).parent))
    from matcher import WatchlistEntry

    try:
        Partner = env["res.partner"]
        partners = Partner.search_read(
            [("clio_obit_watch", "=", True)],
            [
                "name", "birthdate", "city", "street",
                "clio_obit_priority", "clio_obit_notify_email",
                "create_date",
            ],
        )
    except Exception as exc:
        _logger.warning("Kunde inte hämta bevakningslista från Odoo: %s", exc)
        return None

    if not partners:
        _logger.info("Inga bevakade partners i Odoo (clio_obit_watch=True).")
        return {}

    result: dict[str, list[WatchlistEntry]] = {}

    for p in partners:
        fornamn, efternamn = _split_name(p.get("name") or "")
        if not efternamn:
            _logger.debug("Partner %s saknar efternamn — hoppar över.", p.get("id"))
            continue

        # Födelseår från birthdate ("YYYY-MM-DD" eller False)
        fodelsear = None
        bd = p.get("birthdate")
        if bd and isinstance(bd, str) and len(bd) >= 4:
            try:
                fodelsear = int(bd[:4])
            except ValueError:
                pass

        # Hemort: city är primär, street som fallback
        hemort = p.get("city") or None

        prioritet = p.get("clio_obit_priority") or "normal"

        # Notifiera-email: specifik per partner, annars systemstandard
        owner_email = (p.get("clio_obit_notify_email") or "").strip()
        if not owner_email:
            owner_email = default_notify_email
        if not owner_email:
            _logger.debug("Partner %s saknar notify_email och inget default — hoppar över.", p.get("id"))
            continue

        # added_at: create_date från Odoo (ISO-format)
        added_at = p.get("create_date") or ""

        entry = WatchlistEntry(
            efternamn       = efternamn,
            fornamn         = fornamn,
            fodelsear       = fodelsear,
            hemort          = hemort,
            prioritet       = prioritet,
            kalla           = "odoo",
            partner_id      = str(p.get("id", "")),
            added_at        = added_at,
            fodelsear_approx= fodelsear is None,  # approx om födelseår saknas
        )

        result.setdefault(owner_email, []).append(entry)

    total = sum(len(v) for v in result.values())
    _logger.info(
        "Laddade %d bevakningsposter för %d ägare från Odoo.",
        total, len(result),
    )
    return result


def get_partner_odoo_id(env, partner_id_str: str) -> int | None:
    """
    Slår upp Odoo-ID för res.partner via partner_id (str från WatchlistEntry).
    Returnerar None om inte funnen.
    """
    if env is None or not partner_id_str:
        return None
    try:
        pid = int(partner_id_str)
        rows = env["res.partner"].search_read([("id", "=", pid)], ["id"], limit=1)
        return rows[0]["id"] if rows else None
    except Exception:
        return None
