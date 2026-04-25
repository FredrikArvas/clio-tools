"""
clio_obit_announcement.py
Lagrar alla dödsannonser som clio-agent-obit har hämtat.
En rad per annons (deduplicerat på ann_id).

Ersätter seen_announcements-tabellen i state.db.
"""

from __future__ import annotations

import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ClioObitAnnouncement(models.Model):
    _name        = "clio.obit.announcement"
    _description = "Clio Obit — Dödsannons"
    _order       = "published_date desc, first_seen desc"
    _rec_name    = "name"

    ann_id = fields.Char(
        string   = "Annons-ID",
        required = True,
        index    = True,
        copy     = False,
        help     = "Unik nyckel från källan (URL eller guid) — används för deduplicering.",
    )
    name = fields.Char(
        string   = "Namn",
        required = True,
        index    = True,
    )
    source_name = fields.Char(
        string = "Källa",
        index  = True,
        help   = "T.ex. 'familjesidan.se' eller 'minnessidor.fonus.se'.",
    )
    url = fields.Char(
        string = "URL",
        help   = "Länk till annonsen på källsajten.",
    )
    published_date = fields.Date(
        string = "Publicerad",
        index  = True,
    )
    first_seen = fields.Datetime(
        string = "Hämtad av Clio",
        index  = True,
    )
    fodelsear = fields.Integer(
        string = "Födelseår",
        help   = "Extraherat från annonstexten. 0 = okänt.",
    )
    hemort = fields.Char(
        string = "Hemort",
        index  = True,
    )
    body_html = fields.Html(
        string   = "Annonstext",
        sanitize = True,
        help     = "Fullständig annonstext hämtad från detaljsidan.",
    )
    body_snippet = fields.Char(
        string  = "Utdrag",
        compute = "_compute_body_snippet",
        store   = True,
        help    = "Upp till 300 tecken ren text — visas i kanban-kort.",
    )
    image = fields.Binary(
        string     = "Tidningsbild",
        attachment = True,
        help       = "Bild av dödsannonsen om den är publicerad i en tidning.",
    )
    image_filename = fields.Char(string="Bildfilnamn")
    matched = fields.Boolean(
        string  = "Matchad",
        default = False,
        index   = True,
        help    = "True om annonsen matchade minst en bevakad person.",
    )
    match_count = fields.Integer(
        string  = "Träffar",
        compute = "_compute_match_count",
        store   = True,
    )
    match_ids = fields.One2many(
        comodel_name = "clio.obit.match",
        inverse_name = "announcement_id",
        string       = "Matchningar",
    )

    _sql_constraints = [
        ("ann_id_uniq", "UNIQUE(ann_id)", "Annons-ID måste vara unikt."),
    ]

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends("body_html")
    def _compute_body_snippet(self):
        for rec in self:
            if rec.body_html:
                text = re.sub(r"<[^>]+>", " ", rec.body_html)
                text = " ".join(text.split())
                rec.body_snippet = text[:300]
            else:
                rec.body_snippet = ""

    @api.depends("match_ids")
    def _compute_match_count(self):
        for rec in self:
            rec.match_count = len(rec.match_ids)
