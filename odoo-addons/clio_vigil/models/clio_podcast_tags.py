"""
clio_podcast_tags.py
Hjälpmodeller för podcasttaggning: geografiska platser och vittnesbakgrunder.
Används som Many2many-taggar på clio.vigil.item.
"""

from __future__ import annotations

from odoo import fields, models


class ClioPodcastGeo(models.Model):
    _name        = "clio.podcast.geo"
    _description = "Clio Podcast — Geografisk plats"
    _order       = "name"
    _rec_name    = "name"

    code = fields.Char(
        string   = "Kod",
        required = True,
        index    = True,
        copy     = False,
        help     = "Internt nyckelord, t.ex. 'mars', 'north_america', 'ocean'.",
    )
    name = fields.Char(
        string   = "Namn",
        required = True,
        translate = True,
    )

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        "Geo-koden måste vara unik.",
    )


class ClioPodcastBackground(models.Model):
    _name        = "clio.podcast.background"
    _description = "Clio Podcast — Vittnesbakgrund"
    _order       = "name"
    _rec_name    = "name"

    code = fields.Char(
        string   = "Kod",
        required = True,
        index    = True,
        copy     = False,
        help     = "Internt nyckelord, t.ex. 'military', 'experiencer', 'scientific'.",
    )
    name = fields.Char(
        string   = "Namn",
        required = True,
        translate = True,
    )

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        "Bakgrunds-koden måste vara unik.",
    )
