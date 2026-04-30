"""
clio_vigil_source.py
Bevakningskällor: RSS-flöden, YouTube-kanaler och webbsajter.
Speglar YAML-konfigurationen och vigil_sources-tabellen i SQLite.
"""

from __future__ import annotations

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ClioVigilSource(models.Model):
    _name        = "clio.vigil.source"
    _description = "Clio Vigil — Bevakningskälla"
    _order       = "domain, source_type, name"
    _rec_name    = "name"

    name = fields.Char(
        string   = "Namn",
        required = True,
        index    = True,
    )
    domain = fields.Selection(
        selection = [("ufo", "UFO/UAP"), ("ai", "AI-modeller")],
        string    = "Domän",
        required  = True,
        index     = True,
    )
    source_type = fields.Selection(
        selection = [("rss", "RSS"), ("youtube", "YouTube"), ("web", "Webb")],
        string    = "Typ",
        required  = True,
    )
    url = fields.Char(
        string   = "URL",
        required = True,
        index    = True,
        help     = "Feed-URL (RSS), kanal-handle (YouTube) eller startsida (webb).",
    )
    maturity = fields.Selection(
        selection = [
            ("tidig",     "Tidig källa"),
            ("etablerad", "Etablerad"),
            ("akademisk", "Akademisk"),
        ],
        string  = "Mognad",
        default = "tidig",
        help    = "Källkvalitet — metadata, blockerar aldrig insamling.",
    )
    weight = fields.Float(
        string  = "Vikt",
        default = 1.0,
        help    = "Prioritetsmultiplikator (standard 1.0, högt förtroende 1.2+).",
    )
    active = fields.Boolean(
        string  = "Aktiv",
        default = True,
    )
    notes = fields.Text(string="Anteckningar")

    _sql_constraints = [
        ("url_uniq", "UNIQUE(url)", "Käll-URL måste vara unik."),
    ]
