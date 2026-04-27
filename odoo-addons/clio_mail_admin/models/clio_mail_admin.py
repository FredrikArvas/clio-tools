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


def _call_raw(env, path: str, data: dict | None = None) -> dict:
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
    return result


def _call(env, path: str, data: dict | None = None) -> str:
    return _call_raw(env, path, data).get("text", "")


class ClioNccLine(models.TransientModel):
    _name = "clio.ncc.line"
    _description = "Clio NCC-rad"
    _order = "id"

    admin_id   = fields.Many2one("clio.mail.admin", ondelete="cascade")
    nr         = fields.Char(string="Nr")
    sfar       = fields.Char(string="Sfär")
    kodord     = fields.Char(string="Kodord")
    name       = fields.Char(string="Projektnamn")
    ncc_ok     = fields.Boolean(string="NCC")
    status_raw = fields.Char(string="Status")


class ClioWaitingLine(models.TransientModel):
    _name = "clio.waiting.line"
    _description = "Väntande mail"
    _order = "id"

    admin_id      = fields.Many2one("clio.mail.admin", ondelete="cascade")
    selected      = fields.Boolean(string="")
    sender        = fields.Char(string="Avsändare")
    subject       = fields.Char(string="Ämne")
    date_received = fields.Char(string="Datum")
    account       = fields.Char(string="Konto")

    def _decide(self, action: str):
        _call(self.env, "/mail/waiting/decide", {"sender": self.sender, "action": action})
        parent = self.admin_id
        parent.waiting_ids.unlink()
        result = _call_raw(self.env, "/mail/waiting/json")
        vals = [
            {
                "admin_id":      parent.id,
                "sender":        r.get("sender", ""),
                "subject":       r.get("subject", ""),
                "date_received": (r.get("date_received") or "")[:10],
                "account":       r.get("account", ""),
            }
            for r in result.get("waiting", [])
        ]
        self.env["clio.waiting.line"].create(vals)
        return parent._reopen()

    def action_vitlista(self):
        return self._decide("VITLISTA")

    def action_svartlista(self):
        return self._decide("SVARTLISTA")

    def action_behall(self):
        return self._decide("BEHÅLL")


class ClioMailAdmin(models.TransientModel):
    _name = "clio.mail.admin"
    _description = "Clio Mail Admin"

    result_text = fields.Text(string="Resultat", readonly=True)
    ncc_ids     = fields.One2many("clio.ncc.line",    "admin_id", string="Projekt")
    waiting_ids = fields.One2many("clio.waiting.line", "admin_id", string="Väntande")

    # Fält för åtgärder med argument
    email_input       = fields.Char(string="E-post")
    decide_sender     = fields.Char(string="Avsändare")
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

    def action_load_ncc(self):
        result = _call_raw(self.env, "/mail/ncc/lista/json")
        self.ncc_ids.unlink()
        vals = []
        for p in result.get("projects", []):
            vals.append({
                "admin_id":   self.id,
                "nr":         p.get("nr") or "",
                "sfar":       p.get("sfar") or "",
                "kodord":     p.get("kodord") or "",
                "name":       p.get("name") or "",
                "ncc_ok":     bool(p.get("ncc_url")),
                "status_raw": p.get("status") or "",
            })
        self.env["clio.ncc.line"].create(vals)
        return self._reopen()

    def action_load_waiting(self):
        self.waiting_ids.unlink()
        result = _call_raw(self.env, "/mail/waiting/json")
        vals = [
            {
                "admin_id":      self.id,
                "sender":        r.get("sender", ""),
                "subject":       r.get("subject", ""),
                "date_received": (r.get("date_received") or "")[:10],
                "account":       r.get("account", ""),
            }
            for r in result.get("waiting", [])
        ]
        self.env["clio.waiting.line"].create(vals)
        return self._reopen()

    def _bulk_decide(self, action: str):
        selected = self.waiting_ids.filtered("selected")
        if not selected:
            raise UserError("Välj minst ett mail.")
        for line in selected:
            _call(self.env, "/mail/waiting/decide", {"sender": line.sender, "action": action})
        self.waiting_ids.unlink()
        result = _call_raw(self.env, "/mail/waiting/json")
        vals = [
            {
                "admin_id":      self.id,
                "sender":        r.get("sender", ""),
                "subject":       r.get("subject", ""),
                "date_received": (r.get("date_received") or "")[:10],
                "account":       r.get("account", ""),
            }
            for r in result.get("waiting", [])
        ]
        self.env["clio.waiting.line"].create(vals)
        return self._reopen()

    def action_bulk_vitlista(self):
        return self._bulk_decide("VITLISTA")

    def action_bulk_svartlista(self):
        return self._bulk_decide("SVARTLISTA")

    def action_bulk_behall(self):
        return self._bulk_decide("BEHÅLL")

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

    def action_decide_vitlista(self):
        if not self.decide_sender:
            raise UserError("Ange avsändarens e-postadress.")
        self.result_text = _call(self.env, "/mail/waiting/decide", {
            "sender": self.decide_sender,
            "action": "VITLISTA",
        })
        self.decide_sender = False
        return self._reopen()

    def action_decide_svartlista(self):
        if not self.decide_sender:
            raise UserError("Ange avsändarens e-postadress.")
        self.result_text = _call(self.env, "/mail/waiting/decide", {
            "sender": self.decide_sender,
            "action": "SVARTLISTA",
        })
        self.decide_sender = False
        return self._reopen()

    def action_decide_behall(self):
        if not self.decide_sender:
            raise UserError("Ange avsändarens e-postadress.")
        self.result_text = _call(self.env, "/mail/waiting/decide", {
            "sender": self.decide_sender,
            "action": "BEHÅLL",
        })
        self.decide_sender = False
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
