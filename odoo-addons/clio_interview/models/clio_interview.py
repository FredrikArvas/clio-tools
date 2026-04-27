import json
import logging
import urllib.error
import urllib.request

from odoo import api, fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:7200"

_ACCOUNTS = [
    ('clio',    'clio@arvas.international'),
    ('ssf',     'ssf@arvas.international'),
    ('krut',    'krut@arvas.international'),
    ('gtff',    'gtff@arvas.international'),
    ('gtk',     'gtk@arvas.international'),
    ('gsf',     'gsf@arvas.international'),
    ('vimla',   'vimla@arvas.international'),
    ('fredrik', 'fredrik@arvas.international'),
    ('ulrika',  'ulrika@arvas.international'),
]


def _service_url(env) -> str:
    return env["ir.config_parameter"].sudo().get_param(
        "clio.service.url", default=_DEFAULT_URL
    ).rstrip("/")


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
        with urllib.request.urlopen(req, timeout=30) as resp:
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


class ClioInterviewTemplate(models.Model):
    _name = "clio.interview.template"
    _description = "Interview Template"
    _order = "name"

    name             = fields.Char(string="Template Name", required=True)
    subject          = fields.Char(string="Subject", required=True)
    opening_question = fields.Text(string="Opening Question", required=True)
    active           = fields.Boolean(default=True)


class ClioInterviewMessage(models.TransientModel):
    _name = "clio.interview.message"
    _description = "Interview Message"
    _order = "id"

    session_id    = fields.Many2one("clio.interview.session", ondelete="cascade")
    direction     = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")],
        string="Direction",
    )
    sender        = fields.Char(string="Sender")
    body          = fields.Text(string="Message")
    date_received = fields.Char(string="Date")


class ClioInterviewSession(models.Model):
    _name = "clio.interview.session"
    _description = "Interview Session"
    _order = "created_at desc"

    thread_id    = fields.Char(string="Thread ID", readonly=True, index=True)
    partner_id   = fields.Many2one("res.partner", string="Participant")
    participant_email = fields.Char(
        string="Email",
        compute="_compute_participant_email",
        store=True,
        readonly=False,
    )
    account_key  = fields.Selection(
        _ACCOUNTS, string="Account", default="clio",
    )
    status       = fields.Selection(
        [("active", "Active"), ("stopped", "Stopped")],
        string="Status", default="active",
    )
    created_at   = fields.Char(string="Started",    readonly=True)
    updated_at   = fields.Char(string="Updated", readonly=True)
    close_at     = fields.Datetime(
        string="Auto-close",
        help="Clio closes the session, generates a summary and sends it to you.",
    )
    message_ids  = fields.One2many(
        "clio.interview.message", "session_id", string="Messages",
    )
    compose_body  = fields.Text(string="Compose")
    summary_prompt = fields.Text(
        string="Summary Prompt",
        help="Leave empty for default summary.",
    )
    summary_text  = fields.Text(string="Summary", readonly=True)

    @api.depends("partner_id")
    def _compute_participant_email(self):
        for rec in self:
            if rec.partner_id and rec.partner_id.email:
                rec.participant_email = rec.partner_id.email

    @api.model
    def action_sync_sessions(self):
        result = _call_raw(self.env, "/mail/interview/sessions")
        for s in result.get("sessions", []):
            existing = self.search([("thread_id", "=", s["thread_id"])], limit=1)
            vals = {
                "thread_id":         s["thread_id"],
                "participant_email": s["participant_email"],
                "account_key":       s.get("account_key", "clio"),
                "status":            s.get("status", "active"),
                "created_at":        s.get("created_at", ""),
                "updated_at":        s.get("updated_at", ""),
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_load_messages(self):
        self.message_ids.unlink()
        result = _call_raw(self.env, "/mail/interview/thread", {"thread_id": self.thread_id})
        vals = [
            {
                "session_id":    self.id,
                "direction":     m.get("direction", "inbound"),
                "sender":        m.get("sender", ""),
                "body":          m.get("body", "").strip(),
                "date_received": (m.get("date_received") or "")[:16],
            }
            for m in result.get("messages", [])
        ]
        self.env["clio.interview.message"].create(vals)
        return {
            "type":      "ir.actions.act_window",
            "res_model": self._name,
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "current",
        }

    def action_send_message(self):
        if not self.compose_body or not self.compose_body.strip():
            raise UserError("Skriv ett meddelande innan du skickar.")
        if not self.thread_id:
            raise UserError("Sessionen saknar tråd-ID.")
        _call_raw(self.env, "/mail/interview/send_message", {
            "thread_id": self.thread_id,
            "body":      self.compose_body.strip(),
        })
        self.compose_body = False
        return self.action_load_messages()

    def action_summarize(self):
        if not self.thread_id:
            raise UserError("Sessionen har inget tråd-ID.")
        result = _call_raw(self.env, "/mail/interview/summarize", {
            "thread_id": self.thread_id,
            "prompt":    self.summary_prompt or "",
        })
        self.summary_text = result.get("text", "")
        return {
            "type":      "ir.actions.act_window",
            "res_model": self._name,
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "current",
        }

    def action_stop(self):
        _call(self.env, "/mail/interview/stop", {"participant": self.participant_email})
        self.status = "stopped"
        return {
            "type":      "ir.actions.act_window",
            "res_model": self._name,
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "current",
        }

    @api.model
    def _cron_close_expired(self):
        now = fields.Datetime.now()
        expired = self.search([
            ("status", "=", "active"),
            ("close_at", "!=", False),
            ("close_at", "<=", now),
        ])
        for session in expired:
            notify_email = (
                session.create_uid.partner_id.email
                or session.create_uid.email
                or ""
            )
            try:
                result = _call_raw(self.env, "/mail/interview/close_and_summarize", {
                    "thread_id":    session.thread_id,
                    "prompt":       session.summary_prompt or "",
                    "notify_email": notify_email,
                })
                session.summary_text = result.get("text", "")
                session.status = "stopped"
                logger.info(
                    f"[clio_interview] Auto-stängd session {session.thread_id} "
                    f"och sammanfattning skickad till {notify_email}"
                )
            except Exception as e:
                logger.error(
                    f"[clio_interview] Fel vid auto-stängning av {session.thread_id}: {e}"
                )


class ClioInterviewStartWizard(models.TransientModel):
    _name = "clio.interview.start.wizard"
    _description = "Start Interview"

    template_id     = fields.Many2one("clio.interview.template", string="Template")
    custom_subject  = fields.Char(string="Custom Subject")
    custom_question = fields.Text(string="Custom Opening Question")
    partner_ids     = fields.Many2many(
        "res.partner",
        string="Participants",
        help="Select one or more contacts. One session is created per participant.",
    )
    account_key     = fields.Selection(_ACCOUNTS, string="Account", default="clio")
    close_at        = fields.Datetime(
        string="Auto-close",
        help="Leave empty for manual close.",
    )
    result_text     = fields.Text(string="Result", readonly=True)

    def action_start(self):
        subject  = (self.template_id.subject          if self.template_id else self.custom_subject  or "").strip()
        question = (self.template_id.opening_question if self.template_id else self.custom_question or "").strip()
        if not subject or not question:
            raise UserError("Ange ämne och öppningsfråga, eller välj en mall.")
        if not self.partner_ids:
            raise UserError("Välj minst en deltagare.")

        results = []
        for partner in self.partner_ids:
            email = (partner.email or "").strip()
            if not email:
                results.append(f"HOPPAR ÖVER {partner.name}: saknar e-post")
                continue
            try:
                resp = _call(self.env, "/mail/interview/start", {
                    "to":      email,
                    "subject": subject,
                    "context": question,
                    "account": self.account_key or "clio",
                })
                session_vals = {
                    "partner_id":        partner.id,
                    "participant_email": email,
                    "account_key":       self.account_key or "clio",
                    "status":            "active",
                }
                if self.close_at:
                    session_vals["close_at"] = self.close_at
                if resp.get("thread_id"):
                    session_vals["thread_id"] = resp["thread_id"]
                self.env["clio.interview.session"].create(session_vals)
                results.append(f"OK {partner.name} <{email}>")
            except UserError as exc:
                results.append(f"FEL {partner.name}: {exc.args[0]}")

        self.result_text = "\n".join(results)
        return {
            "type":      "ir.actions.act_window",
            "res_model": self._name,
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "new",
        }
