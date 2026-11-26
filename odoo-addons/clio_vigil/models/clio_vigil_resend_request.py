"""
clio_vigil_resend_request.py
Begäran om att skicka om ett datum-digest till en prenumerant.
Skapas från guiden i Odoo; bearbetas av clio-vigil --resend på servern.
"""

from __future__ import annotations

from odoo import fields, models


class ClioVigilResendRequest(models.Model):
    _name        = "clio.vigil.resend.request"
    _description = "Clio Vigil — Skicka om utskick"
    _rec_name    = "subscriber_id"
    _order       = "created_at desc"

    subscriber_id = fields.Many2one(
        "clio.vigil.subscriber",
        string   = "Prenumerant",
        required = True,
        ondelete = "cascade",
        index    = True,
    )
    digest_date = fields.Date(
        string   = "Digestdatum",
        required = True,
    )
    state = fields.Selection(
        selection = [
            ("pending", "Väntar"),
            ("sent",    "Skickad"),
            ("failed",  "Misslyckad"),
        ],
        string   = "Status",
        default  = "pending",
        required = True,
        index    = True,
    )
    created_at = fields.Datetime(
        string   = "Skapad",
        default  = fields.Datetime.now,
        readonly = True,
    )
    sent_at = fields.Datetime(string="Skickad",    readonly=True)
    result  = fields.Char(   string="Resultat",    readonly=True,
                             help="Ex. '5 objekt skickade' eller felorsak.")

    _sub_date_uniq = models.Constraint(
        "UNIQUE(subscriber_id, digest_date)",
        "En pending eller skickad begäran för denna prenumerant och detta datum finns redan.",
    )
