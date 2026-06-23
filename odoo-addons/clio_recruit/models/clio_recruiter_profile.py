"""
clio_recruiter_profile.py
Rekryterarprofil för passiv kandidatsourcing.
En profil per rekryteringsuppdrag (t.ex. "CapFM SAP-rekrytering").
"""

import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class ClioRecruiterProfile(models.Model):
    _name        = "clio.recruiter.profile"
    _description = "Clio Recruit — Rekryterarprofil"
    _order       = "name"
    _rec_name    = "name"

    name = fields.Char(
        string   = "Profilnamn",
        required = True,
        index    = True,
        help     = "Internt namn för uppdraget, t.ex. 'CapFM SAP-rekrytering'.",
    )
    email = fields.Char(
        string = "Mottagaradress",
        help   = "E-post dit Clio skickar signalrapporter.",
    )
    language = fields.Selection(
        selection = [("sv", "Svenska"), ("en", "English")],
        string    = "Rapportspråk",
        default   = "sv",
    )
    target_role = fields.Char(
        string = "Målroll",
        help   = "T.ex. 'Senior SAP-arkitekt / SAP-konsult'.",
    )
    target_seniority = fields.Char(
        string = "Senioritetsnivå",
        help   = "T.ex. 'Senior (10+ år)'.",
    )
    target_characteristics = fields.Text(
        string = "Kandidatkaraktäristik",
        help   = "Egenskaper att leta efter — en per rad.",
    )
    target_avoid = fields.Text(
        string = "Undvik",
        help   = "Profiler att exkludera — en per rad.",
    )
    target_industries = fields.Text(
        string = "Målbranscher",
        help   = "Branscher att bevaka — en per rad.",
    )
    trigger_signals_high = fields.Text(
        string = "Högvärda signaler",
        help   = "Marknadshändelser med hög sannolikhet för kandidattillgång — en per rad.",
    )
    trigger_signals_medium = fields.Text(
        string = "Medelvärda signaler",
        help   = "Marknadshändelser att bevaka sekundärt — en per rad.",
    )
    confidential_client = fields.Boolean(
        string  = "Konfidentiell klient",
        default = True,
        help    = "Dölj klientnamn i utskickade rapporter.",
    )
    client_hint = fields.Char(
        string = "Klientbeskrivning",
        help   = "Hur klienten beskrivs i rapporter om konfidentiell, t.ex. 'ett ledande konsultbolag'.",
    )
    active = fields.Boolean(
        string  = "Aktiv",
        default = True,
    )
    match_ids = fields.One2many(
        comodel_name = "clio.recruiter.match",
        inverse_name = "profile_id",
        string       = "Matchhistorik",
    )
    match_count = fields.Integer(
        string  = "Matchningar",
        compute = "_compute_match_count",
        store   = False,
    )

    def _compute_match_count(self):
        for rec in self:
            rec.match_count = len(rec.match_ids)

    def action_view_matches(self):
        self.ensure_one()
        return {
            "type":     "ir.actions.act_window",
            "name":     "Matchhistorik",
            "res_model": "clio.recruiter.match",
            "view_mode": "list,form",
            "domain":   [("profile_id", "=", self.id)],
            "context":  {"default_profile_id": self.id},
        }
