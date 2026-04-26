"""
odoo_reader.py
Läser bevakningslistan från Odoo via clio.obit.watch.
Returnerar samma dict-struktur som _load_all_watchlists() i run.py
så att resten av koden inte behöver ändras.

Kräver: clio_odoo/connection.py + ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD i .env
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
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
    Hämtar aktiva bevakningsposter från Odoo via clio.obit.watch.

    Returnerar Dict {owner_email: [WatchlistEntry, ...]} — samma format som
    _load_all_watchlists(). None om anslutning misslyckades.
    """
    if env is None:
        return None

    sys.path.insert(0, str(Path(__file__).parent))
    from matcher import WatchlistEntry

    try:
        watches = env["clio.obit.watch"].search_read(
            [],
            [
                "partner_id", "user_id", "priority",
                "notify_email", "effective_email",
                "partner_name", "partner_birth_name",
                "create_date",
            ],
        )
    except Exception as exc:
        _logger.warning("Kunde inte hämta bevakningslista från Odoo: %s", exc)
        return None

    if not watches:
        _logger.info("Inga bevakningsrelationer i Odoo.")
        return {}

    # Bulk-hämta födelseår och hemort från res.partner
    partner_ids = list({w["partner_id"][0] for w in watches if w.get("partner_id")})
    partners_by_id: dict[int, dict] = {}
    try:
        prows = env["res.partner"].read(
            partner_ids, ["id", "clio_obit_birth_year", "city"]
        )
        partners_by_id = {p["id"]: p for p in prows}
    except Exception as exc:
        _logger.warning("Kunde inte läsa partner-data: %s", exc)

    result: dict[str, list[WatchlistEntry]] = {}

    for w in watches:
        if not w.get("partner_id") or not w.get("user_id"):
            continue

        partner_id   = w["partner_id"][0]
        partner_name = w.get("partner_name") or ""
        birth_name   = w.get("partner_birth_name") or ""

        # Föredra födelsenamn för matchning om det skiljer sig
        name_for_match = birth_name if birth_name else partner_name
        fornamn, efternamn = _split_name(name_for_match)
        if not efternamn:
            fornamn, efternamn = _split_name(partner_name)
        if not efternamn:
            _logger.debug("Partner %d saknar efternamn — hoppar över.", partner_id)
            continue

        pdata     = partners_by_id.get(partner_id, {})
        fodelsear = pdata.get("clio_obit_birth_year") or None
        if fodelsear == 0:
            fodelsear = None
        hemort    = pdata.get("city") or None

        prioritet   = w.get("priority") or "normal"
        owner_email = (w.get("effective_email") or "").strip()
        if not owner_email:
            owner_email = default_notify_email
        if not owner_email:
            _logger.debug("Watch %d saknar e-post — hoppar över.", w.get("id", 0))
            continue

        added_at = w.get("create_date") or datetime.now(timezone.utc).isoformat()

        entry = WatchlistEntry(
            efternamn        = efternamn,
            fornamn          = fornamn,
            fodelsear        = fodelsear,
            hemort           = hemort,
            prioritet        = prioritet,
            kalla            = "odoo",
            partner_id       = str(partner_id),
            added_at         = added_at,
            fodelsear_approx = fodelsear is None,
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
    """
    if env is None or not partner_id_str:
        return None
    try:
        pid = int(partner_id_str)
        rows = env["res.partner"].search_read([("id", "=", pid)], ["id"], limit=1)
        return rows[0]["id"] if rows else None
    except Exception:
        return None
