"""
clio_vigil_wizard_resend.py
Guide för att skicka om ett datumspecifikt digest till en eller flera prenumeranter.
Nås via Actions-menyn i listan eller knappen i formulärvyn.
"""

from __future__ import annotations

from datetime import timedelta

from odoo import api, fields, models


class ClioVigilResendWizard(models.TransientModel):
    _name        = "clio.vigil.resend.wizard"
    _description = "Clio Vigil — Skicka om utskick"

    subscriber_ids = fields.Many2many(
        "clio.vigil.subscriber",
        string   = "Prenumeranter",
        readonly = True,
    )
    subscriber_count = fields.Integer(
        string  = "Antal prenumeranter",
        compute = "_compute_subscriber_count",
    )
    digest_date = fields.Date(
        string   = "Digestdatum",
        required = True,
        default  = lambda self: fields.Date.today() - timedelta(days=1),
        help     = "Datum för det utskick som ska skickas om.",
    )

    @api.depends("subscriber_ids")
    def _compute_subscriber_count(self):
        for rec in self:
            rec.subscriber_count = len(rec.subscriber_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "subscriber_ids" in fields_list:
            active_ids = self.env.context.get("active_ids", [])
            if active_ids:
                res["subscriber_ids"] = [(6, 0, active_ids)]
        return res

    def action_confirm(self):
        """
        Skapar skicka-om-begäranden för varje vald prenumerant.
        Om en pending/skickad begäran redan finns för samma datum hoppas den över.
        Misslyckade försök återställs till pending.
        """
        self.ensure_one()
        Request = self.env["clio.vigil.resend.request"]
        created = 0

        for sub in self.subscriber_ids:
            existing = Request.search([
                ("subscriber_id", "=", sub.id),
                ("digest_date",   "=", self.digest_date),
            ], limit=1)

            if existing:
                if existing.state == "failed":
                    existing.write({"state": "pending", "result": False, "sent_at": False})
                    created += 1
                # pending/sent: hoppa över (dubletten ger inget värde)
            else:
                Request.create({
                    "subscriber_id": sub.id,
                    "digest_date":   self.digest_date,
                })
                created += 1

        return {"type": "ir.actions.act_window_close"}
