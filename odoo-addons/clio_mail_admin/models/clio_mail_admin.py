import json
import logging
import urllib.error
import urllib.request

from odoo import api, fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:7200"


def _service_url(env) -> str:
    param = env["ir.config_parameter"].sudo().get_param(
        "clio.service.url", default=_DEFAULT_URL
    )
    return param.rstrip("/")


def _call(env, path: str, data: dict | None = None) -> str:
    base = _service_url(env)
    url = f"{base}{path}"
    method = "POST" if data is not None else "GET"
    body = json.dumps(data or {}).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise UserError(f"Kunde inte nå clio-service ({base}): {e.reason}")
    except Exception as e:
        raise UserError(f"clio-service fel: {e}")

    if not result.get("ok"):
        raise UserError(result.get("error", "Okänt fel från clio-service"))
    return result.get("text", "")


class ClioMailAdmin(models.TransientModel):
    _name = "clio.mail.admin"
    _description = "Clio Mail Admin"

    result_text = fields.Text(string="Resultat", readonly=True)

    # Fält för åtgärder med argument
    email_input      = fields.Char(string="E-post")
    interview_to      = fields.Char(string="Till")
    interview_subject = fields.Char(string="Ämne", default="Intervju")
    interview_context = fields.Text(string="Kontext")

    # ── Enkla kommandon ───────────────────────────────────────────────────────

    def action_list(self):
        self.result_text = _call(self.env, "/mail/list")
        return self._reopen()

    def action_waiting(self):
        self.result_text = _call(self.env, "/mail/waiting")
        return self._reopen()

    def action_status(self):
        self.result_text = _call(self.env, "/mail/status")
        return self._reopen()

    def action_whitelist(self):
        self.result_text = _call(self.env, "/mail/whitelist")
        return self._reopen()

    def action_ncc_lista(self):
        self.result_text = _call(self.env, "/mail/ncc/lista")
        return self._reopen()

    # ── Kommandon med argument ────────────────────────────────────────────────

    def action_whitelist_add(self):
        if not self.email_input:
            raise UserError("Ange en e-postadress att vitlista.")
        self.result_text = _call(self.env, "/mail/whitelist", {"email": self.email_input})
        self.email_input = False
        return self._reopen()

    def action_blacklist(self):
        if not self.email_input:
            raise UserError("Ange en e-postadress att svartlista.")
        self.result_text = _call(self.env, "/mail/blacklist", {"email": self.email_input})
        self.email_input = False
        return self._reopen()

    def action_interview_start(self):
        if not self.interview_to:
            raise UserError("Ange mottagarens e-postadress.")
        self.result_text = _call(self.env, "/mail/interview/start", {
            "to":      self.interview_to,
            "subject": self.interview_subject or "Intervju",
            "context": self.interview_context or "",
        })
        return self._reopen()

    def action_interview_stop(self):
        if not self.interview_to:
            raise UserError("Ange deltagarens e-postadress.")
        self.result_text = _call(self.env, "/mail/interview/stop", {
            "participant": self.interview_to,
        })
        self.interview_to = False
        return self._reopen()

    # ── Hjälpmetod ────────────────────────────────────────────────────────────

    def _reopen(self):
        return {
            "type":      "ir.actions.act_window",
            "res_model": self._name,
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "new",
        }
