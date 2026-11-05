"""
clio_recruiter_profile.py
Rekryterarprofil för passiv kandidatsourcing.
En profil per rekryteringsuppdrag (t.ex. "CapFM SAP-rekrytering").
"""

import logging
import subprocess
import sys
from odoo import fields, models, api

_logger = logging.getLogger(__name__)

_AGENT_SCRIPT = "/home/clioadmin/19.0/clio-tools/clio-agent-job/run.py"


class ClioRecruiterProfile(models.Model):
    _name        = "clio.recruiter.profile"
    _description = "Clio Recruit — Rekryterarprofil"
    _order       = "name"
    _rec_name    = "name"
    _inherit     = ["mail.thread", "mail.activity.mixin"]

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

    def action_run_manual_search(self):
        """Startar manuell artikelsökning i bakgrunden. Resultat syns i Matchhistorik-fliken."""
        self.ensure_one()
        if not self.email:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {"message": "Profilen saknar mottagaradress.", "type": "warning"},
            }

        try:
            subprocess.Popen(
                [sys.executable, _AGENT_SCRIPT, "--odoo-recruiter-id", str(self.id)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self.message_post(
                body=f"<b>Manuell sökning — fel vid start</b><br/><pre>{exc}</pre>",
                subject=f"Manuell sökning — {self.name}",
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {"message": f"Kunde inte starta sökningen: {exc}", "type": "danger"},
            }

        self.message_post(
            body="<b>Manuell sökning startad</b> — resultaten sparas i Matchhistorik-fliken när klart (ca 5–10 min).",
            subject=f"Manuell sökning — {self.name}",
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": "Sökning startad — se Matchhistorik när klart.", "type": "success"},
        }

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
