"""
clio_job_article.py
Lagrar alla artiklar som clio-agent-job har sett och analyserat.
En rad per artikel (deduplicerat på article_id).

Ersätter seen_articles-tabellen i SQLite.
"""

from __future__ import annotations

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ClioJobArticle(models.Model):
    _name        = "clio.job.article"
    _description = "Clio Job — Sedda artiklar"
    _order       = "first_seen desc"
    _rec_name    = "title"

    article_id = fields.Char(
        string   = "Article ID",
        required = True,
        index    = True,
        copy     = False,
        help     = "SHA256-hash av URL — unik nyckel för deduplicering.",
    )
    url = fields.Char(string="URL")
    title = fields.Char(string="Title")
    source = fields.Char(string="Source", index=True)
    published = fields.Datetime(
        string = "Published",
        index  = True,
        help   = "Artikelns publiceringsdatum enligt källan.",
    )
    first_seen = fields.Datetime(string="Fetched", index=True)
    body_snippet = fields.Text(
        string = "Snippet",
        help   = "Upp till 1 000 tecken brödtext från artikeln.",
    )
    match_score = fields.Integer(
        string  = "Score",
        default = -1,
        index   = True,
        help    = "0–100 från AI-analysen. -1 = ej analyserad (fel).",
    )
    is_matched = fields.Boolean(
        string = "Matched",
        default = False,
        index   = True,
        help    = "True om score ≥ tröskel och markerad relevant av AI.",
    )

    _sql_constraints = [
        ("article_id_uniq", "UNIQUE(article_id)", "Artikel-ID måste vara unikt."),
    ]

    # ── Beräknade fält ────────────────────────────────────────────────────────

    score_display = fields.Char(
        string  = "Score",
        compute = "_compute_score_display",
        store   = False,
        help    = "Visar '—' för ej analyserade, annars score i %.",
    )

    @api.depends("match_score")
    def _compute_score_display(self):
        for rec in self:
            if rec.match_score < 0:
                rec.score_display = "—"
            else:
                rec.score_display = f"{rec.match_score} %"
