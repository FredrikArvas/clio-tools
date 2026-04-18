"""
res_partner.py
Utökar res.partner med en flagg för jobbsignalbevakning och länk till profil.
"""

from odoo import models, fields


class ResPartner(models.Model):
    _inherit = "res.partner"

    clio_job_watch = fields.Boolean(
        string="Bevaka jobsignaler",
        default=False,
        help="Flagga för Clio job-agent: skicka förändringssignaler till den här personen.",
    )
    clio_job_profile_ids = fields.One2many(
        comodel_name="clio.job.profile",
        inverse_name="partner_id",
        string="Clio Job-profiler",
    )
