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
        selection = [("rss", "RSS"), ("youtube", "YouTube"), ("web", "Webb"),
                     ("google_news", "Google News")],
        string    = "Typ",
        required  = True,
    )
    language = fields.Selection(
        selection = [
            ("en",    "Engelska"),
            ("sv",    "Svenska"),
            ("pt",    "Portugisiska"),
            ("multi", "Flerspråkig"),
        ],
        string    = "Språk",
        required  = True,
        default   = "en",
        help      = "Transkriptionsspråk — styr val av AI-modell. "
                    "Flerspråkig = auto-detect per avsnitt.",
    )
    url = fields.Char(
        string   = "URL",
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

    # ── Källspecifika fält ───────────────────────────────────────────────────
    channel_id = fields.Char(
        string = "YouTube Channel ID",
        help   = "t.ex. UCxxxxxxxxxxxxxxxxxxxxxxxx — hämtas automatiskt från kanal-URL.",
    )
    google_news_query = fields.Char(
        string = "Google News-sökterm",
        help   = "Fritextsökning som matas till Google News RSS.",
    )
    auth_env = fields.Char(
        string = "Auth-env-nyckel",
        help   = "Miljövariabel med USER:PASSWORD för autentiserade RSS-flöden.",
    )
    transcription_threshold = fields.Float(
        string  = "Transkribtionströskel",
        default = 0.0,
        help    = "Override av domänstandard — 0.0 = använd domänens värde.",
    )

    # ── Sprint C: Arkivering ─────────────────────────────────────────────────
    archive_enabled = fields.Boolean(
        string  = "Arkivera lokalt",
        default = False,
        help    = "Om aktiverad laddar --archive-sources ned hela källarkivet.",
    )
