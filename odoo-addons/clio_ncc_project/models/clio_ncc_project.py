"""
clio_ncc_project.py — Projektlista med NCC-status

Persistent model (inte Transient) — data stannar kvar mellan sessioner.
Uppdateras manuellt via "Ladda om"-knapp som anropar clio-service.

Uppdateringslogiken (schemalagd synk, webhooks etc.) hanteras i separat session.
"""

import json
import logging
import urllib.error
import urllib.request

from odoo import api, fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:7200"


def _service_url(env) -> str:
    return env["ir.config_parameter"].sudo().get_param(
        "clio.service.url", default=_DEFAULT_URL
    ).rstrip("/")


def _call_raw(env, path: str) -> dict:
    url = f"{_service_url(env)}{path}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise UserError(f"Kunde inte nå clio-service: {e.reason}")
    except Exception as e:
        raise UserError(f"clio-service fel: {e}")
    if not result.get("ok"):
        raise UserError(result.get("error", "Okänt fel från clio-service"))
    return result


class ClioNccProject(models.Model):
    _name = "clio.ncc.project"
    _description = "Clio — Projektlista (NCC)"
    _order = "nr"
    _rec_name = "name"

    nr         = fields.Char(string="Nr", index=True)
    sfar       = fields.Char(string="Sfär")
    kodord     = fields.Char(string="Kodord", index=True)
    name       = fields.Char(string="Projektnamn", required=True)
    ncc_ok     = fields.Boolean(string="NCC", default=False)
    notion_url = fields.Char(string="Notion")
    status_raw = fields.Char(string="Status")

    @api.model
    def action_reload_from_service(self):
        """
        Hämtar projektlistan från clio-service och uppdaterar databasen.
        Befintliga rader raderas och återskapas (full refresh).
        """
        result = _call_raw(self.env, "/mail/ncc/lista/json")
        projects = result.get("projects", [])

        self.search([]).unlink()

        vals_list = [
            {
                "nr":         p.get("nr") or "",
                "sfar":       p.get("sfar") or "",
                "kodord":     p.get("kodord") or "",
                "name":       p.get("name") or "(inget namn)",
                "ncc_ok":     bool(p.get("ncc_url")),
                "notion_url": p.get("ncc_url") or "",
                "status_raw": p.get("status") or "",
            }
            for p in projects
        ]
        self.create(vals_list)

        return {
            "type": "ir.actions.client",
            "tag":  "reload",
        }
