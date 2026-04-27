"""
clio_job_profile.py
Profildata för en jobbsökande kandidat kopplad till res.partner.
En partner kan ha max en aktiv profil (active=True).
"""

from odoo import models, fields


class ClioJobProfile(models.Model):
    _name        = "clio.job.profile"
    _description = "Clio Job — Kandidatprofil"
    _order       = "partner_id"
    _rec_name    = "partner_id"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contact",
        required=True,
        ondelete="cascade",
        index=True,
        help="Den res.partner-post som profilen tillhör.",
    )
    report_email = fields.Char(
        string="Report Email",
        help="E-postadress dit Clio skickar signalrapporter. "
             "Lämnas tomt → används partner-e-posten.",
    )
    role = fields.Char(
        string="Current Role",
        help="Personens nuvarande jobbtitel eller roll.",
    )
    seniority = fields.Char(
        string="Seniority Level",
        help='T.ex. "Senior / Executive", "Junior", "Mid".',
    )
    geography = fields.Char(
        string="Geography",
        help='Region eller stad, t.ex. "Stockholm".',
    )
    hybrid_ok = fields.Boolean(
        string="Hybrid OK",
        default=True,
        help="Kandidaten är öppen för hybridarbete.",
    )
    background = fields.Text(
        string="Background",
        help="Karriärhistorik och erfarenheter — en post per rad.",
    )
    education = fields.Text(
        string="Education",
        help="Utbildningar och grader — en post per rad.",
    )
    target_roles = fields.Text(
        string="Target Roles",
        help="Roller som kandidaten söker — en per rad.",
    )
    signal_keywords = fields.Text(
        string="Signal Keywords",
        help="Nyckelord som Clio bevakar i nyhetsflöden — ett per rad.\n"
             'T.ex. "ny GD", "digital transformation", "förvärv".',
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Avmarkera för att arkivera profilen utan att radera den.",
    )
    match_ids = fields.One2many(
        comodel_name="clio.job.match",
        inverse_name="profile_id",
        string="Match History",
    )
    match_count = fields.Integer(
        string="Match Count",
        compute="_compute_match_count",
        store=False,
    )

    def _compute_match_count(self):
        for rec in self:
            rec.match_count = len(rec.match_ids)
