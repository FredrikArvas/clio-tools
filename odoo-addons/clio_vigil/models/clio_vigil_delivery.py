"""
clio_vigil_delivery.py
Leveranspost: ett bevakningsobjekt skickat till en prenumerant.
Skapas av clio-vigil notifier.py efter skickad digest.
"""

from __future__ import annotations

from odoo import fields, models


class ClioVigilDelivery(models.Model):
    _name        = "clio.vigil.delivery"
    _description = "Clio Vigil — Leverans"
    _rec_name    = "item_id"
    _order       = "delivered_at desc"

    subscriber_id = fields.Many2one(
        "clio.vigil.subscriber",
        string   = "Prenumerant",
        required = True,
        ondelete = "cascade",
        index    = True,
    )
    item_id = fields.Many2one(
        "clio.vigil.item",
        string   = "Objekt",
        required = True,
        ondelete = "cascade",
    )
    delivered_at = fields.Datetime(string="Skickad",      required=True)
    digest_date  = fields.Date(   string="Digestdatum")

    _sql_constraints = [
        (
            "sub_item_uniq",
            "UNIQUE(subscriber_id, item_id)",
            "Objektet har redan levererats till denna prenumerant.",
        ),
    ]
