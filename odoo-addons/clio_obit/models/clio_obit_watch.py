"""
clio_obit_watch.py
Bevakningsrelation: en res.users bevakar en res.partner för dödsannonser.

En person kan bevakas av flera användare med individuell prioritet och
notifieringsadress. Ersätter de gamla fälten clio_obit_priority och
clio_obit_notify_email på res.partner.
"""

from __future__ import annotations

from odoo import api, fields, models


class ClioObitWatch(models.Model):
    _name        = "clio.obit.watch"
    _description = "Clio Obit — Bevakningsrelation"
    _order       = "partner_name, priority"
    _rec_name    = "partner_id"

    partner_id = fields.Many2one(
        comodel_name = "res.partner",
        string       = "Person",
        required     = True,
        ondelete     = "cascade",
        domain       = [("is_company", "=", False)],
        index        = True,
    )
    user_id = fields.Many2one(
        comodel_name = "res.users",
        string       = "Bevakare",
        required     = True,
        ondelete     = "cascade",
        default      = lambda self: self.env.user,
        index        = True,
    )
    priority = fields.Selection(
        selection = [
            ("viktig",       "Viktig — direkt notis"),
            ("normal",       "Normal — daglig digest"),
            ("bra_att_veta", "Bra att veta"),
        ],
        string   = "Prioritet",
        default  = "normal",
        required = True,
    )
    notify_email = fields.Char(
        string = "Notifiera e-post",
        help   = "Lämnas tomt = användarens e-postadress används.",
    )
    effective_email = fields.Char(
        string  = "Effektiv e-post",
        compute = "_compute_effective_email",
    )

    # Denormaliserade fält för effektiv listvy
    partner_name = fields.Char(
        related = "partner_id.name",
        string  = "Namn",
        store   = True,
    )
    partner_birth_name = fields.Char(
        related = "partner_id.clio_obit_birth_name",
        string  = "Födelsenamn",
        store   = True,
    )

    _sql_constraints = [
        (
            "partner_user_uniq",
            "UNIQUE(partner_id, user_id)",
            "Du bevakar redan den här personen.",
        ),
    ]

    @api.depends("notify_email", "user_id", "user_id.email")
    def _compute_effective_email(self):
        for rec in self:
            rec.effective_email = rec.notify_email or rec.user_id.email or ""
