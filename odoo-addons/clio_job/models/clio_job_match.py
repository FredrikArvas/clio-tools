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
        string="Kandidatprofil",
        required=True,
        ondelete="cascade",
        index=True,
    )
    article_url = fields.Char(
        string="Artikel-URL",
    )
    article_title = fields.Char(
        string="Rubrik",
    )
    signal_type = fields.Char(
        string="Signaltyp",
        help='T.ex. "ny_gd", "förvärv", "digitaliseringsprogram".',
    )
    match_score = fields.Integer(
        string="Matchningspoäng",
        help="0–100. Rapport skickades vid poäng ≥ konfigurerat tröskel (default 50).",
    )
    sent_at = fields.Datetime(
        string="Skickad",
        help="Tidsstämpel för när rapporten skickades till kandidaten.",
    )
    recommended_action = fields.Char(
        string="Rekommenderad åtgärd",
        help='T.ex. "kontakta_nu", "bevaka_3_mån".',
    )
