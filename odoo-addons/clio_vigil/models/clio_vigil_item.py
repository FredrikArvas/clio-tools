"""
clio_vigil_item.py
Pipeline-objekt: artiklar, podcastavsnitt och YouTube-klipp som passerar
genom clio-vigils bearbetningskedja (filter → transkription → RAG → digest).
Speglar vigil_items-tabellen i SQLite.
"""

from __future__ import annotations

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ClioVigilItem(models.Model):
    _name        = "clio.vigil.item"
    _description = "Clio Vigil — Bevakningsobjekt"
    _order       = "priority_score desc, published_at desc"
    _rec_name    = "title"

    # ── Identifiering ────────────────────────────────────────────────────────

    url = fields.Char(
        string   = "URL",
        required = True,
        index    = True,
        copy     = False,
    )
    title = fields.Char(string="Titel")

    # ── Källmetadata ─────────────────────────────────────────────────────────

    domain = fields.Selection(
        selection = [("ufo", "UFO/UAP"), ("ai", "AI-modeller")],
        string    = "Domän",
        index     = True,
    )
    source_type = fields.Selection(
        selection = [("rss", "RSS"), ("youtube", "YouTube"), ("web", "Webb")],
        string    = "Källtyp",
    )
    source_name = fields.Char(string="Källa", index=True)
    source_maturity = fields.Selection(
        selection = [
            ("tidig",     "Tidig källa"),
            ("etablerad", "Etablerad"),
            ("akademisk", "Akademisk"),
        ],
        string = "Mognad",
    )
    published_at = fields.Datetime(
        string = "Publicerat",
        index  = True,
    )
    duration_seconds = fields.Integer(
        string = "Längd (s)",
        help   = "Längd i sekunder. Tomt för webb/PDF.",
    )

    # ── Poäng och prioritet ──────────────────────────────────────────────────

    relevance_score = fields.Float(
        string = "Relevansscore",
        digits = (5, 4),
        help   = "0.0–1.0 från nyckelordsfiltret.",
    )
    priority_score = fields.Float(
        string = "Prioritet",
        digits = (5, 4),
        index  = True,
        help   = "Relevansscore × källvikt × längdfaktor × tidsfaktor.",
    )

    # ── Tillstånd ────────────────────────────────────────────────────────────

    state = fields.Selection(
        selection = [
            ("discovered",  "Hittad"),
            ("filtered_in", "Passerade filter"),
            ("filtered_out","Filtrerades bort"),
            ("queued",      "I kö"),
            ("transcribing","Transkriberas"),
            ("transcribed", "Transkriberad"),
            ("indexed",     "Indexerad"),
            ("notified",    "Skickad i digest"),
        ],
        string  = "Tillstånd",
        default = "discovered",
        index   = True,
    )

    # ── Innehåll ─────────────────────────────────────────────────────────────

    summary = fields.Text(
        string = "Sammanfattning",
        help   = "2–3 meningar från Claude API.",
    )
    transcript_snippet = fields.Text(
        string = "Transkript (utdrag)",
        help   = "Första 500 tecken av transkriptionen.",
    )

    # ── Tidsstämplar ─────────────────────────────────────────────────────────

    created_at  = fields.Datetime(string="Skapad",       copy=False)
    notified_at = fields.Datetime(string="Notifierad",   copy=False)

    _sql_constraints = [
        ("url_uniq", "UNIQUE(url)", "Objekt-URL måste vara unik."),
    ]

    # ── Åtgärder ─────────────────────────────────────────────────────────────

    def action_boost(self):
        """Boostar objektet till toppen av transkriptionskön (prio 999)."""
        self.ensure_one()
        self.write({
            "priority_score": 999.0,
            "state": "queued",
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Boostade!",
                "message": f"'{self.title or self.url[:60]}' boostad till toppen av kön.",
                "type": "success",
                "sticky": False,
            },
        }

    def action_reset_to_discovered(self):
        """Återställer objektet till discovered (börja om)."""
        self.ensure_one()
        self.write({
            "state": "discovered",
            "priority_score": 0.0,
        })
