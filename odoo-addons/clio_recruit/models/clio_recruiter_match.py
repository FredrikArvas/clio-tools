"""
clio_recruiter_match.py
En matchningspost per signalartikel per rekryterarprofil.
Skapas av clio-recruiter när en artikel når matchtröskel och rapport skickats.
"""

from odoo import fields, models


class ClioRecruiterMatch(models.Model):
    _name        = "clio.recruiter.match"
    _description = "Clio Recruit — Matchad signal"
    _order       = "sent_at desc"
    _rec_name    = "article_title"

    profile_id = fields.Many2one(
        comodel_name = "clio.recruiter.profile",
        string       = "Rekryterarprofil",
        required     = True,
        ondelete     = "cascade",
        index        = True,
    )
    article_url = fields.Char(
        string = "Artikel-URL",
    )
    article_title = fields.Char(
        string = "Artikelrubrik",
    )
    target_company = fields.Char(
        string = "Bolag",
        index  = True,
        help   = "Bolaget som signalen gäller.",
    )
    candidate_profile = fields.Char(
        string = "Kandidattyp",
        help   = "Typ av SAP-person som berörs av signalen.",
    )
    signal_type = fields.Char(
        string = "Signaltyp",
        help   = "T.ex. plattformsbyte, outsourcing, varsel, s4hana_migration, cio_byte.",
    )
    match_score = fields.Integer(
        string = "Score",
        help   = "0–100 från AI-analysen.",
    )
    estimated_timeline = fields.Char(
        string = "Tidshorisont",
        help   = "Uppskattad tid tills kandidater kan bli tillgängliga, t.ex. '3–6 månader'.",
    )
    contact_hint = fields.Char(
        string = "Kontakttips",
        help   = "Rekommenderat sätt att nå potentiella kandidater.",
    )
    recommended_action = fields.Char(
        string = "Rekommenderad åtgärd",
        help   = "T.ex. kontakta_nu, bevaka_3_mån, skip.",
    )
    sent_at = fields.Datetime(
        string = "Rapport skickad",
        index  = True,
        help   = "Tidsstämpel för när rapporten skickades.",
    )
