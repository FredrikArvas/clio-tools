"""
odoo_reader.py — clio-vigil
============================
Läser tillståndsändringar från Odoo och tillämpar dem på SQLite.

Konfliktlösning: senaste ändring vinner.
  - Odoos write_date > SQLites state_updated_at → Odoo skriver till SQLite
  - SQLites state_updated_at >= Odoos write_date → SQLite behålls (Odoo synkas nästa körning)

Kraschsäkert: SQLite är alltid källa till sanning. Om Odoo-läsning misslyckas
loggas en varning och pipeline fortsätter oförändrad.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_logger = logging.getLogger(__name__)

# Fält som får skrivas från Odoo → SQLite
_SYNC_FIELDS = ("state", "priority_score")

# Tillstånd som är giltiga att ta emot från Odoo
_VALID_STATES = {
    "discovered", "filtered_in", "filtered_out",
    "queued", "transcribing", "transcribed",
    "indexed", "notified",
}


def _parse_dt(s: str | bool) -> str:
    """Normaliserar datum/tid till 'YYYY-MM-DD HH:MM:SS' eller '1970-01-01 00:00:00'."""
    if not s:
        return "1970-01-01 00:00:00"
    return str(s)[:19].replace("T", " ")


def pull_state_changes(odoo_env, conn) -> int:
    """
    Hämtar tillståndsändringar från Odoo och tillämpar dem på SQLite.

    Logik per objekt:
      1. Jämför Odoos write_date med SQLites state_updated_at.
      2. Om Odoo är nyare och state/priority_score skiljer sig → uppdatera SQLite.
      3. Annars behålls SQLites värde.

    Returnerar antal SQLite-rader som uppdaterades.
    """
    if odoo_env is None:
        return 0

    try:
        rows_odoo = odoo_env["clio.vigil.item"].search_read(
            [],
            ["url", "state", "priority_score", "write_date"],
        )
    except Exception as exc:
        _logger.warning("pull_state_changes: kunde inte läsa från Odoo: %s", exc)
        return 0

    if not rows_odoo:
        return 0

    updated = 0

    for item in rows_odoo:
        url           = item.get("url", "")
        odoo_state    = item.get("state", "")
        odoo_prio     = float(item.get("priority_score") or 0.0)
        odoo_write_dt = _parse_dt(item.get("write_date"))

        if not url or odoo_state not in _VALID_STATES:
            continue

        try:
            row = conn.execute(
                "SELECT id, state, priority_score, state_updated_at "
                "FROM vigil_items WHERE url = ?",
                (url,),
            ).fetchone()
        except Exception as exc:
            _logger.warning("pull_state_changes: SQLite-läsfel för %s: %s", url[:60], exc)
            continue

        if row is None:
            continue

        sqlite_updated_at = _parse_dt(row["state_updated_at"])

        # Odoo är nyare — tillämpa på SQLite
        if odoo_write_dt > sqlite_updated_at:
            changed = False

            if odoo_state != row["state"]:
                conn.execute(
                    "UPDATE vigil_items SET state = ?, state_updated_at = ? WHERE id = ?",
                    (odoo_state, _now(), row["id"]),
                )
                _logger.info(
                    "pull_state_changes: %s  %s → %s (Odoo vann)",
                    url[:60], row["state"], odoo_state,
                )
                changed = True

            if abs(odoo_prio - float(row["priority_score"] or 0.0)) > 0.001:
                conn.execute(
                    "UPDATE vigil_items SET priority_score = ? WHERE id = ?",
                    (odoo_prio, row["id"]),
                )
                _logger.info(
                    "pull_state_changes: prio %s → %.3f (Odoo vann)",
                    url[:60], odoo_prio,
                )
                changed = True

            if changed:
                conn.commit()
                updated += 1

    if updated:
        _logger.info("pull_state_changes: %d SQLite-rader uppdaterade från Odoo", updated)

    return updated


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_subscribers(odoo_env) -> list[dict]:
    """
    Läser aktiva prenumeranter från Odoo.

    Returnerar lista med dicts:
        id, email, follows_ufo, follows_ai,
        keywords: [{keyword, weight, domain}, ...]
    """
    if odoo_env is None:
        return []

    try:
        subs = odoo_env["clio.vigil.subscriber"].search_read(
            [("active", "=", True)],
            ["id", "partner_id", "email", "follows_ufo", "follows_ai", "keyword_ids"],
        )
    except Exception as exc:
        _logger.warning("load_subscribers: kunde inte läsa prenumeranter: %s", exc)
        return []

    result = []
    for s in subs:
        # Effektiv e-post: explicit override eller hämta från partner
        email = s.get("email") or ""
        if not email:
            partner = s.get("partner_id")
            if partner and isinstance(partner, (list, tuple)):
                try:
                    p = odoo_env["res.partner"].search_read(
                        [("id", "=", partner[0])], ["email"], limit=1
                    )
                    if p:
                        email = p[0].get("email") or ""
                except Exception:
                    pass

        # Sökord
        keywords = []
        kw_ids = s.get("keyword_ids", [])
        if kw_ids:
            try:
                kw_rows = odoo_env["clio.vigil.keyword"].search_read(
                    [("id", "in", kw_ids)],
                    ["keyword", "weight", "domain"],
                )
                keywords = [
                    {"keyword": k["keyword"], "weight": k["weight"], "domain": k["domain"]}
                    for k in kw_rows
                ]
            except Exception as exc:
                _logger.warning(
                    "load_subscribers: sökord för prenumerant %d: %s", s["id"], exc
                )

        result.append({
            "id":          s["id"],
            "email":       email,
            "follows_ufo": bool(s.get("follows_ufo")),
            "follows_ai":  bool(s.get("follows_ai")),
            "keywords":    keywords,
        })

    _logger.info("load_subscribers: %d aktiva prenumeranter laddade", len(result))
    return result
