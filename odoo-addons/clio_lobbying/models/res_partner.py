"""
res_partner.py — clio_lobbying
Utökar res.partner med en Journalist-flik som visar
bevakade artiklar (clio.vigil.item) och skickade pitchar (clio.lobbying.pitch).
"""

from __future__ import annotations

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ── Journalist-länk ──────────────────────────────────────────────────────

    journalist_id = fields.One2many(
        comodel_name="clio.lobbying.journalist",
        inverse_name="partner_id",
        string="Journalistprofil",
    )
    is_journalist = fields.Boolean(
        string="Är journalist",
        compute="_compute_is_journalist",
        store=True,
    )

    @api.depends("journalist_id")
    def _compute_is_journalist(self):
        for rec in self:
            rec.is_journalist = bool(rec.journalist_id)

    # ── Beräknade relationer ─────────────────────────────────────────────────

    lobbying_pitch_ids = fields.Many2many(
        comodel_name="clio.lobbying.pitch",
        string="Pitchar",
        compute="_compute_lobbying_data",
    )
    lobbying_pitch_count = fields.Integer(
        string="Antal pitchar",
        compute="_compute_lobbying_data",
    )
    vigil_article_ids = fields.Many2many(
        comodel_name="clio.vigil.item",
        string="Bevakade artiklar",
        compute="_compute_lobbying_data",
    )
    vigil_article_count = fields.Integer(
        string="Antal artiklar",
        compute="_compute_lobbying_data",
    )

    @api.depends("journalist_id")
    def _compute_lobbying_data(self):
        for rec in self:
            if not rec.journalist_id:
                rec.lobbying_pitch_ids   = self.env["clio.lobbying.pitch"].browse([])
                rec.lobbying_pitch_count = 0
                rec.vigil_article_ids    = self.env["clio.vigil.item"].browse([])
                rec.vigil_article_count  = 0
                continue

            journalist = rec.journalist_id[0]

            pitches = self.env["clio.lobbying.pitch"].search(
                [("journalist_id", "=", journalist.id)]
            )
            rec.lobbying_pitch_ids   = pitches
            rec.lobbying_pitch_count = len(pitches)

            articles = self.env["clio.vigil.item"].search(
                [("source_name", "=", journalist.publication)],
                limit=50,
                order="published_at desc",
            )
            rec.vigil_article_ids   = articles
            rec.vigil_article_count = len(articles)

    # ── Åtgärd ───────────────────────────────────────────────────────────────

    def action_create_journalist(self):
        """Skapar en journalistprofil kopplad till denna kontakt."""
        self.ensure_one()
        return {
            "type":      "ir.actions.act_window",
            "res_model": "clio.lobbying.journalist",
            "view_mode": "form",
            "context": {
                "default_partner_id": self.id,
                "default_name":       self.name,
                "default_email":      self.email or "",
            },
        }
