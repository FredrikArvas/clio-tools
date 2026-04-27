"""
clio_job_match.py
En matchningspost som Clio skapar varje gång en artikel når tröskeln
och en rapport skickas till kandidaten.
"""

from odoo import models, fields


class ClioJobMatch(models.Model):
    _name        = "clio.job.match"
    _description = "Clio Job — Matchad signal"
    _order       = "sent_at desc"
    _rec_name    = "article_title"

    profile_id = fields.Many2one(
        comodel_name="clio.job.profile",
        string="Candidate Profile",
        required=True,
        ondelete="cascade",
        index=True,
    )
    article_url = fields.Char(
        string="Article URL",
    )
    article_title = fields.Char(
        string="Title",
    )
    signal_type = fields.Char(
        string="Signal Type",
        help='T.ex. "ny_gd", "förvärv", "digitaliseringsprogram".',
    )
    match_score = fields.Integer(
        string="Match Score",
        help="0–100. Rapport skickades vid poäng ≥ konfigurerat tröskel (default 50).",
    )
    sent_at = fields.Datetime(
        string="Sent",
        help="Tidsstämpel för när rapporten skickades till kandidaten.",
    )
    recommended_action = fields.Char(
        string="Recommended Action",
        help='T.ex. "kontakta_nu", "bevaka_3_mån".',
    )
