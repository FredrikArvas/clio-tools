"""
odoo_writer.py
Skriver körningsresultat från clio-agent-obit till Odoo:
  - clio.obit.announcement  — en post per ny annons (ersätter state.db)
  - clio.obit.match         — en post per matchad annons per bevakad person
  - clio.tool.heartbeat     — en post per körning (upsert på tool_name)

Kraschsäkert: Odoo är ett extra lager, inte ett hårdberoende.
Om anslutning saknas eller misslyckas loggas en varning och körningen fortsätter.

Kräver i .env: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
"""

from __future__ import annotations

import base64
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matcher import Announcement, Match

_logger = logging.getLogger(__name__)

TOOL_NAME = "clio-agent-obit"

_ROOT = Path(__file__).parent.parent
for _p in [str(_ROOT), str(_ROOT / "clio_odoo")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _utcnow_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_odoo_env():
    """Returnerar en ansluten OdooConnector, eller None vid fel."""
    try:
        from clio_odoo import connect
        return connect()
    except Exception as exc:
        _logger.warning("Odoo-anslutning misslyckades: %s", exc)
        return None


def check_cross_source_duplicates(env, announcements: list) -> dict[str, int]:
    """
    Söker efter korsvis källduplikat: samma person publicerad på flera sajter.
    Returnerar {ann_id: canonical_odoo_id} för annonser som troligen är duplikat.

    Algoritm: för varje ny annons, kolla om Odoo redan har en annons med
    samma efternamn + förnamn från en ANNAN källa inom de senaste 14 dagarna.
    """
    if env is None or not announcements:
        return {}
    from datetime import date, timedelta
    date_from = (date.today() - timedelta(days=14)).isoformat()
    result: dict[str, int] = {}
    try:
        for ann in announcements:
            namn = getattr(ann, "namn", "") or ""
            source = getattr(ann, "source_name", "") or ""
            if not namn or not source:
                continue
            words = namn.strip().split()
            if len(words) < 2:
                continue
            last_name  = words[-1]
            first_name = words[0]
            existing = env["clio.obit.announcement"].search_read([
                ("name", "ilike", last_name),
                ("source_name", "!=", source),
                ("source_name", "!=", False),
                "|",
                ("published_date", "=", False),
                ("published_date", ">=", date_from),
            ], ["id", "name", "source_name"], limit=5)
            for rec in existing:
                if first_name.lower() in (rec["name"] or "").lower():
                    result[ann.id] = rec["id"]
                    _logger.info(
                        "Duplikat: %r (%s) ≈ Odoo#%d (%s)",
                        namn, source, rec["id"], rec["source_name"],
                    )
                    break
    except Exception as exc:
        _logger.warning("check_cross_source_duplicates misslyckades: %s", exc)
    return result


def bulk_load_seen_ann_ids(env) -> set[str]:
    """
    Hämtar alla kända annons-IDs från Odoo i en enda bulk-fråga.
    Används för deduplicering INNAN matchning — ett anrop istället för N.

    Returnerar tomt set om Odoo inte är tillgängligt.
    """
    if env is None:
        return set()
    try:
        rows = env["clio.obit.announcement"].search_read([], ["ann_id"])
        ids = {r["ann_id"] for r in rows}
        _logger.debug("bulk_load_seen_ann_ids: %d kända IDs", len(ids))
        return ids
    except Exception as exc:
        _logger.warning("Kunde inte hämta annons-IDs från Odoo: %s", exc)
        return set()


def save_announcement(env, ann, duplicate_of_id: int | None = None) -> int | None:
    """
    Skapar clio.obit.announcement om ann_id inte redan finns.

    Args:
        env:              OdooConnector
        ann:              Announcement-objekt från matcher.py
        duplicate_of_id:  Odoo-ID för kanonisk annons om denna är ett duplikat

    Returns:
        Odoo-postens ID (int), eller None vid fel / om den redan finns.
    """
    if env is None:
        return None
    try:
        Announcement = env["clio.obit.announcement"]

        # Kontrollera om posten redan existerar (dubbelsäkring)
        existing = Announcement.search_read(
            [("ann_id", "=", ann.id)], ["id"], limit=1
        )
        if existing:
            return existing[0]["id"]

        # Födelseår: 0 om okänt
        fodelsear = ann.fodelsear or 0

        # Publicerat datum
        pub_date = ann.publiceringsdatum or None
        if pub_date and len(pub_date) >= 10:
            pub_date = pub_date[:10]  # "YYYY-MM-DD"
        else:
            pub_date = None

        source = getattr(ann, "source_name", "") or ""

        vals = {
            "ann_id":         ann.id,
            "name":           ann.namn or ann.raw_title or "Okänt namn",
            "source_name":    source,
            "url":            ann.url or "",
            "published_date": pub_date,
            "first_seen":     _utcnow_str(),
            "fodelsear":      fodelsear,
            "hemort":         ann.hemort or "",
            "matched":        False,
        }
        if duplicate_of_id:
            vals["duplicate_of"] = duplicate_of_id

        # Annonstext och bild (sätts om de är hämtade)
        if getattr(ann, "body_html", ""):
            vals["body_html"] = ann.body_html
        if getattr(ann, "image_data", None):
            vals["image"] = base64.b64encode(ann.image_data).decode("ascii")
            vals["image_filename"] = _image_filename(ann)

        odoo_id = Announcement.create(vals)
        _logger.debug("Skapade announcement %s → Odoo ID %s", ann.id, odoo_id)
        return odoo_id

    except Exception as exc:
        _logger.warning("Kunde inte spara annons i Odoo: %s", exc)
        return None


def update_announcement_detail(
    env,
    odoo_id: int,
    body_html: str = "",
    image_data: bytes = None,
    image_filename: str = "",
    matched: bool = True,
) -> None:
    """
    Uppdaterar en befintlig clio.obit.announcement med detaljdata
    (annonstext, bild, matchningsstatus).
    """
    if env is None or not odoo_id:
        return
    try:
        vals: dict = {"matched": matched}
        if body_html:
            vals["body_html"] = body_html
        if image_data:
            vals["image"] = base64.b64encode(image_data).decode("ascii")
            vals["image_filename"] = image_filename or "annons.jpg"
        env["clio.obit.announcement"].write([odoo_id], vals)
    except Exception as exc:
        _logger.warning("Kunde inte uppdatera annons %s i Odoo: %s", odoo_id, exc)


def save_match(
    env,
    announcement_odoo_id: int,
    partner_odoo_id: int,
    score: int,
    priority: str,
    notified_at: str | None = None,
    suppressed: bool = False,
) -> None:
    """
    Skapar clio.obit.match och kopplar partnern till mentioned_partner_ids
    på annonsen (för retroaktiv sökning).
    """
    """
    Skapar clio.obit.match för en matchad annons.

    Args:
        announcement_odoo_id: Odoo-ID för clio.obit.announcement
        partner_odoo_id:      Odoo-ID för res.partner (den bevakade personen)
        score:                Konfidenspoäng
        priority:             "viktig" | "normal" | "bra_att_veta"
        notified_at:          ISO-sträng för notistidpunkt (None = ej notifierad)
        suppressed:           True om grace-period träffade in
    """
    if env is None or not announcement_odoo_id or not partner_odoo_id:
        return
    try:
        env["clio.obit.match"].create({
            "announcement_id": announcement_odoo_id,
            "partner_id":      partner_odoo_id,
            "score":           score,
            "priority":        priority,
            "notified_at":     notified_at,
            "suppressed":      suppressed,
        })
        # Lägg till partnern i nämnda personer på annonsen
        env["clio.obit.announcement"].write(
            [announcement_odoo_id],
            {"mentioned_partner_ids": [(4, partner_odoo_id)]},
        )
    except Exception as exc:
        _logger.warning("Kunde inte spara match i Odoo: %s", exc)


def write_heartbeat(
    env,
    status: str,
    items_processed: int = 0,
    message: str = "",
) -> None:
    """Upsert clio.tool.heartbeat för clio-agent-obit."""
    if env is None:
        return
    try:
        Heartbeat = env["clio.tool.heartbeat"]
        vals = {
            "last_run":        _utcnow_str(),
            "status":          status,
            "items_processed": int(items_processed),
            "message":         (message or "")[:255],
        }
        existing = Heartbeat.search_read(
            [("tool_name", "=", TOOL_NAME)], ["id"], limit=1
        )
        if existing:
            Heartbeat.write([existing[0]["id"]], vals)
        else:
            vals["tool_name"] = TOOL_NAME
            Heartbeat.create(vals)
        _logger.info("Heartbeat: %s → %s", TOOL_NAME, status)
    except Exception as exc:
        _logger.warning("Kunde inte skriva heartbeat: %s", exc)


def _image_filename(ann) -> str:
    safe_name = (ann.namn or "annons").replace(" ", "_").replace("/", "_")
    return f"obit_{safe_name}.jpg"
