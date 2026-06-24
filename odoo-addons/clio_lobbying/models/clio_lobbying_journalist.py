"""
clio_lobbying_journalist.py
Journalist-databas för Clio Lobbying.
Populeras automatiskt av clio-vigil byline-extraktion via odoo_writer.
Kontaktuppgifter och anteckningar curateras manuellt.
"""

from __future__ import annotations

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ClioLobbyingJournalist(models.Model):
    _name        = "clio.lobbying.journalist"
    _description = "Clio Lobbying — Journalist"
    _order       = "article_count desc, name"
    _rec_name    = "display_name"

    # ── Identifiering ────────────────────────────────────────────────────────

    name = fields.Char(string="Namn", required=True, index=True)
    publication = fields.Char(string="Publikation", required=True, index=True)

    display_name = fields.Char(
        string="Visningsnamn",
        compute="_compute_display_name",
        store=True,
    )

    @api.depends("name", "publication")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} ({rec.publication})" if rec.publication else rec.name

    # ── Kontakt ──────────────────────────────────────────────────────────────

    email = fields.Char(
        string="E-post",
        help="Manuellt ifyllt. Krävs för pitch-sändning via pipeline.",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Kontakt",
        ondelete="set null",
        help="Länk till Odoo-kontakt. Koppla manuellt eller via 'Skapa kontakt'.",
    )

    # ── Domän och ämnen ──────────────────────────────────────────────────────

    domain = fields.Selection(
        selection=[("ufo", "UFO/UAP"), ("ai", "AI-modeller")],
        string="Domän",
        index=True,
    )
    topics = fields.Char(
        string="Ämnesord",
        help="Kommaseparerade nyckelord extraherade från journalistens artiklar.",
    )

    # ── Profil ───────────────────────────────────────────────────────────────

    profile = fields.Text(
        string="Intresseprofil",
        help="Genereras av Claude utifrån journalistens senaste bevakade artiklar.",
    )
    notes = fields.Text(
        string="Anteckningar",
        help="Relationsnoteringar, preferenser, senaste kontakt m.m.",
    )

    # ── Statistik (skrivs av pipeline) ───────────────────────────────────────

    article_count = fields.Integer(
        string="Artiklar",
        default=0,
        readonly=True,
        help="Antal bevakade artiklar hittade av clio-vigil.",
    )
    last_seen_at = fields.Datetime(
        string="Senast sedd",
        readonly=True,
        help="Datum för senaste bevakade artikel.",
    )
    pitch_count = fields.Integer(
        string="Pitchar",
        compute="_compute_pitch_count",
    )

    @api.depends("pitch_ids")
    def _compute_pitch_count(self):
        for rec in self:
            rec.pitch_count = len(rec.pitch_ids)

    pitch_ids = fields.One2many(
        comodel_name="clio.lobbying.pitch",
        inverse_name="journalist_id",
        string="Pitchar",
    )

    # ── Tillstånd ────────────────────────────────────────────────────────────

    state = fields.Selection(
        selection=[
            ("active",   "Aktiv"),
            ("paused",   "Pausad"),
            ("archived", "Arkiverad"),
        ],
        string="Status",
        default="active",
        index=True,
    )

    _sql_constraints = [
        ("name_publication_uniq", "UNIQUE(name, publication)",
         "Journalist + publikation måste vara unik."),
    ]

    # ── Åtgärder ─────────────────────────────────────────────────────────────

    def action_create_partner(self):
        """Skapar eller kopplar en res.partner från journalistposten."""
        self.ensure_one()
        if self.partner_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "res.partner",
                "res_id": self.partner_id.id,
                "view_mode": "form",
            }
        partner = self.env["res.partner"].create({
            "name": self.name,
            "email": self.email or False,
            "comment": f"Journalist — {self.publication}",
        })
        self.partner_id = partner
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": partner.id,
            "view_mode": "form",
        }

    def action_view_articles(self):
        """Öppnar vigil-objekt för denna journalists publikation."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Artiklar — {self.name}",
            "res_model": "clio.vigil.item",
            "view_mode": "list,form",
            "domain": [("source_name", "=", self.publication)],
        }

    def action_view_pitches(self):
        """Öppnar alla pitch-utkast för denna journalist."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Pitchar — {self.name}",
            "res_model": "clio.lobbying.pitch",
            "view_mode": "list,form",
            "domain": [("journalist_id", "=", self.id)],
        }
