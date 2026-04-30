"""
clio_vigil_subscriber.py
Prenumerant på clio-vigil digest — kopplad till en res.partner.
"""

from __future__ import annotations

from odoo import api, fields, models


class ClioVigilSubscriber(models.Model):
    _name        = "clio.vigil.subscriber"
    _description = "Clio Vigil — Prenumerant"
    _rec_name    = "partner_id"
    _order       = "partner_id"

    partner_id = fields.Many2one(
        "res.partner",
        string    = "Kontakt",
        required  = True,
        ondelete  = "cascade",
        index     = True,
    )
    email = fields.Char(
        string = "E-post (override)",
        help   = "Lämna tomt för att använda kontaktens e-postadress.",
    )
    effective_email = fields.Char(
        string  = "E-post",
        compute = "_compute_effective_email",
        store   = False,
    )
    active = fields.Boolean(string="Aktiv", default=True)

    follows_ufo = fields.Boolean(string="UFO/UAP",      default=False)
    follows_ai  = fields.Boolean(string="AI-modeller",  default=False)

    keyword_ids = fields.One2many(
        "clio.vigil.keyword", "subscriber_id",
        string = "Sökord",
    )
    delivery_ids = fields.One2many(
        "clio.vigil.delivery", "subscriber_id",
        string = "Leveranser",
    )
    delivery_count = fields.Integer(
        string  = "Antal leveranser",
        compute = "_compute_delivery_count",
    )

    _sql_constraints = [
        ("partner_uniq", "UNIQUE(partner_id)", "Kontakten har redan en prenumeration."),
    ]

    @api.depends("email", "partner_id.email")
    def _compute_effective_email(self):
        for rec in self:
            rec.effective_email = rec.email or rec.partner_id.email or ""

    @api.depends("delivery_ids")
    def _compute_delivery_count(self):
        for rec in self:
            rec.delivery_count = len(rec.delivery_ids)
