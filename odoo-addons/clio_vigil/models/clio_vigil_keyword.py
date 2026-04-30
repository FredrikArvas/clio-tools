"""
clio_vigil_keyword.py
Prenumerantspecifikt sökord med viktning och valfri domänbegränsning.
"""

from __future__ import annotations

from odoo import fields, models


class ClioVigilKeyword(models.Model):
    _name        = "clio.vigil.keyword"
    _description = "Clio Vigil — Sökord"
    _rec_name    = "keyword"
    _order       = "subscriber_id, keyword"

    subscriber_id = fields.Many2one(
        "clio.vigil.subscriber",
        string   = "Prenumerant",
        required = True,
        ondelete = "cascade",
        index    = True,
    )
    keyword = fields.Char(string="Sökord", required=True)
    weight  = fields.Selection(
        selection = [
            ("primary",   "Primär (0.4)"),
            ("secondary", "Sekundär (0.15)"),
        ],
        string   = "Vikt",
        default  = "primary",
        required = True,
    )
    domain = fields.Selection(
        selection = [
            ("ufo", "UFO/UAP"),
            ("ai",  "AI-modeller"),
            ("all", "Alla domäner"),
        ],
        string  = "Domän",
        default = "all",
    )
