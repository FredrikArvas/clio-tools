from odoo import api, fields, models
from odoo.exceptions import UserError

from .clio_mail_admin import _call, _call_raw


class ClioInterviewTemplate(models.Model):
    _name = "clio.interview.template"
    _description = "Intervjumall"
    _order = "name"

    name             = fields.Char(string="Mallnamn", required=True)
    subject          = fields.Char(string="Ämne", required=True)
    opening_question = fields.Text(string="Öppningsfråga", required=True)
    active           = fields.Boolean(default=True)


class ClioInterviewMessage(models.TransientModel):
    _name = "clio.interview.message"
    _description = "Intervjumeddelande"
    _order = "id"

    session_id    = fields.Many2one("clio.interview.session", ondelete="cascade")
    direction     = fields.Selection(
        [("inbound", "Inkommande"), ("outbound", "Utgående")],
        string="Riktning",
    )
    sender        = fields.Char(string="Avsändare")
    body          = fields.Text(string="Meddelande")
    date_received = fields.Char(string="Datum")


class ClioInterviewSession(models.Model):
    _name = "clio.interview.session"
    _description = "Intervjusession"
    _order = "created_at desc"

    thread_id         = fields.Char(string="Tråd-ID", readonly=True, index=True)
    participant_email = fields.Char(string="Deltagare")
    account_key       = fields.Char(string="Konto")
    status            = fields.Selection(
        [("active", "Aktiv"), ("stopped", "Avslutad")],
        string="Status", default="active",
    )
    created_at  = fields.Char(string="Startad", readonly=True)
    updated_at  = fields.Char(string="Uppdaterad", readonly=True)
    message_ids = fields.One2many(
        "clio.interview.message", "session_id", string="Dialog",
    )

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
                "body":          m.get("body", ""),
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


class ClioInterviewStartWizard(models.TransientModel):
    _name = "clio.interview.start.wizard"
    _description = "Starta intervju"

    template_id     = fields.Many2one("clio.interview.template", string="Mall")
    custom_subject  = fields.Char(string="Eget ämne")
    custom_question = fields.Text(string="Egen öppningsfråga")
    recipients      = fields.Text(
        string="Mottagare",
        help="En e-postadress per rad. Samma fråga skickas till alla.",
    )
    result_text     = fields.Text(string="Resultat", readonly=True)

    def action_start(self):
        subject  = (self.template_id.subject          if self.template_id else self.custom_subject  or "").strip()
        question = (self.template_id.opening_question if self.template_id else self.custom_question or "").strip()
        if not subject or not question:
            raise UserError("Ange ämne och öppningsfråga, eller välj en mall.")

        raw    = self.recipients or ""
        emails = [
            e.strip()
            for e in raw.replace(",", "\n").splitlines()
            if e.strip() and "@" in e
        ]
        if not emails:
            raise UserError("Ange minst en e-postadress.")

        results = []
        for email in emails:
            try:
                _call(self.env, "/mail/interview/start", {
                    "to":      email,
                    "subject": subject,
                    "context": question,
                })
                results.append(f"✅ {email}")
            except UserError as exc:
                results.append(f"❌ {email}: {exc.args[0]}")

        self.result_text = "\n".join(results)
        # Sync sessions so new ones appear in the list
        self.env["clio.interview.session"].action_sync_sessions()
        return {
            "type":      "ir.actions.act_window",
            "res_model": self._name,
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "new",
        }
