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
        string   = "Artikel-ID",
        required = True,
        index    = True,
        copy     = False,
        help     = "SHA256-hash av URL — unik nyckel för deduplicering.",
    )
    url = fields.Char(string="URL")
    title = fields.Char(string="Rubrik")
    source = fields.Char(string="Källa", index=True)
    first_seen = fields.Datetime(string="Först sedd", index=True)
    match_score = fields.Integer(
        string  = "Matchning",
        default = -1,
        help    = "0–100 från AI-analysen. -1 = ej analyserad (fel).",
    )
    is_matched = fields.Boolean(
        string = "Matchad",
        default = False,
        index   = True,
        help    = "True om score ≥ tröskel och markerad relevant av AI.",
    )

    _sql_constraints = [
        ("article_id_uniq", "UNIQUE(article_id)", "Artikel-ID måste vara unikt."),
    ]

    # ── Beräknade fält ────────────────────────────────────────────────────────

    score_label = fields.Char(
        string   = "Score",
        compute  = "_compute_score_label",
        store    = False,
    )

    @api.depends("match_score")
    def _compute_score_label(self):
        for rec in self:
            if rec.match_score < 0:
                rec.score_label = "—"
            else:
                rec.score_label = f"{rec.match_score} %"
