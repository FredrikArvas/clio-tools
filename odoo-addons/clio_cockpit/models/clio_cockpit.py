import json
import logging
import urllib.error
import urllib.request

from odoo import fields, models
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://172.18.0.1:7200"


def _service_url(env) -> str:
    return env["ir.config_parameter"].sudo().get_param(
        "clio.service.url", default=_DEFAULT_URL
    ).rstrip("/")


def _call(env, path: str, data: dict | None = None) -> dict:
    base = _service_url(env)
    url  = f"{base}{path}"
    body = json.dumps(data or {}).encode() if data is not None else None
    req  = urllib.request.Request(
        url, data=body,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise UserError(f"Kunde inte nå clio-service ({base}): {e.reason}")
    except Exception as e:
        raise UserError(f"clio-service fel: {e}")
    if not result.get("ok"):
        raise UserError(result.get("error", "Okänt fel från clio-service"))
    return result


class ClioCockpit(models.TransientModel):
    _name        = "clio.cockpit"
    _description = "Clio Cockpit"
    _rec_name    = "display_name"

    display_name = fields.Char(default="Clio Cockpit", readonly=True)

    # ── Agentstatus ───────────────────────────────────────────────────────────
    agent_status = fields.Text(string="Agentstatus", readonly=True)

    # ── RAG ───────────────────────────────────────────────────────────────────
    rag_query  = fields.Char(string="Fråga")
    rag_mode   = fields.Selection([
        ("books", "Böcker"),
        ("ncc",   "Context Cards (NCC)"),
    ], string="Källa", default="books")
    rag_result = fields.Text(string="Svar", readonly=True)

    # ── Bibliotek ─────────────────────────────────────────────────────────────
    library_query  = fields.Char(string="Sök titel / författare")
    library_result = fields.Text(string="Träffar", readonly=True)

    # ── Server ────────────────────────────────────────────────────────────────
    server_summary      = fields.Text(string="Systeminformation", readonly=True)
    server_updates      = fields.Text(string="Tillgängliga uppdateringar", readonly=True)
    server_last_checked = fields.Datetime(string="Senast kontrollerad", readonly=True)

    # ── Mail Admin ────────────────────────────────────────────────────────────
    mail_result       = fields.Text(string="Resultat", readonly=True)
    email_input       = fields.Char(string="E-post")
    decide_sender     = fields.Char(string="Avsändare")
    interview_to      = fields.Char(string="Till")
    interview_subject = fields.Char(string="Ämne", default="Intervju")
    interview_context = fields.Text(string="Kontext")

    # ── Agentstatus ───────────────────────────────────────────────────────────

    def action_refresh_status(self):
        result = _call(self.env, "/agents/status")
        agents = result.get("agents", {})
        lines  = []
        icons  = {True: "✅", False: "❌"}
        for key, info in agents.items():
            icon = icons.get(info.get("active", False), "❓")
            extra = ""
            if key == "rag" and info.get("active"):
                parts = []
                if info.get("books"): parts.append("böcker")
                if info.get("ncc"):   parts.append("NCC")
                if parts: extra = f"  [{', '.join(parts)}]"
            lines.append(f"{icon}  {info.get('label', key)}  {info.get('status', '')}{extra}")
        self.agent_status = "\n".join(lines)
        return self._reopen()

    # ── Server ────────────────────────────────────────────────────────────────

    def action_refresh_server(self):
        from odoo import fields as odoo_fields
        r = _call(self.env, "/health/server")

        cpu   = r.get("cpu_percent", "?")
        ram_u = r.get("ram_used_gb", "?")
        ram_t = r.get("ram_total_gb", "?")
        ram_p = r.get("ram_percent", "?")
        disk_u = r.get("disk_used_gb", "?")
        disk_t = r.get("disk_total_gb", "?")
        disk_p = r.get("disk_percent", "?")
        days   = r.get("uptime_days", 0)
        hours  = r.get("uptime_hours", 0)

        self.server_summary = (
            f"CPU      {cpu} %\n"
            f"RAM      {ram_u} / {ram_t} GB  ({ram_p} %)\n"
            f"Disk     {disk_u} / {disk_t} GB  ({disk_p} %)\n"
            f"Uptime   {days} dagar  {hours} timmar"
        )

        updates = r.get("updates", [])
        count   = r.get("updates_count", 0)
        if updates:
            self.server_updates = f"{count} uppdateringar:\n" + "\n".join(f"  • {u}" for u in updates)
        else:
            self.server_updates = "✅  Inga väntande uppdateringar"

        self.server_last_checked = odoo_fields.Datetime.now()
        return self._reopen()

    # ── RAG ───────────────────────────────────────────────────────────────────

    def action_rag_search(self):
        if not self.rag_query:
            raise UserError("Skriv en fråga först.")
        result = _call(self.env, "/rag/query", {
            "q":   self.rag_query,
            "top": 5,
            "ncc": self.rag_mode == "ncc",
        })
        # Strippa markdown-formattering (** och *)
        import re as _re
        answer = _re.sub(r'\*\*(.+?)\*\*', r'\1', result.get("text", ""))
        answer = _re.sub(r'\*(.+?)\*', r'\1', answer)

        sources = result.get("sources", [])
        if sources:
            # Deduplicera på (title, page_start, page_end)
            seen = set()
            unique = []
            for s in sources:
                key = (s.get("title"), s.get("page_start"), s.get("page_end"))
                if key not in seen:
                    seen.add(key)
                    unique.append(s)

            src_lines = ["\n─── Källor ───"]
            for s in unique:
                score = s.get("score", "")
                title = s.get("title", "?")
                if s.get("page_start"):
                    pages = f"s. {s['page_start']}"
                    if s.get("page_end") and s["page_end"] != s["page_start"]:
                        pages += f"–{s['page_end']}"
                    src_lines.append(f"  [{score}] {title}, {pages}")
                else:
                    url = s.get("url", "")
                    src_lines.append(f"  [{score}] {title}  {url}")
            answer += "\n".join(src_lines)
        self.rag_result = answer
        return self._reopen()

    # ── Bibliotek ─────────────────────────────────────────────────────────────

    def action_library_search(self):
        if not self.library_query:
            raise UserError("Skriv en sökning först.")
        result = _call(self.env, "/library/search", {"q": self.library_query})
        self.library_result = result.get("text", "")
        return self._reopen()

    # ── Mail Admin ────────────────────────────────────────────────────────────

    def _mail(self, path, data=None):
        self.mail_result = _call(self.env, path, data).get("text", "")
        return self._reopen()

    def action_list(self):       return self._mail("/mail/list")
    def action_waiting(self):    return self._mail("/mail/waiting")
    def action_status(self):     return self._mail("/mail/status")
    def action_whitelist(self):  return self._mail("/mail/whitelist")
    def action_ncc_lista(self):  return self._mail("/mail/ncc/lista")

    def action_whitelist_add(self):
        if not self.email_input:
            raise UserError("Ange en e-postadress.")
        res = self._mail("/mail/whitelist", {"email": self.email_input})
        self.email_input = False
        return res

    def action_blacklist(self):
        if not self.email_input:
            raise UserError("Ange en e-postadress.")
        res = self._mail("/mail/blacklist", {"email": self.email_input})
        self.email_input = False
        return res

    def action_decide_vitlista(self):
        if not self.decide_sender:
            raise UserError("Ange avsändarens e-postadress.")
        res = self._mail("/mail/waiting/decide", {
            "sender": self.decide_sender, "action": "VITLISTA"})
        self.decide_sender = False
        return res

    def action_decide_svartlista(self):
        if not self.decide_sender:
            raise UserError("Ange avsändarens e-postadress.")
        res = self._mail("/mail/waiting/decide", {
            "sender": self.decide_sender, "action": "SVARTLISTA"})
        self.decide_sender = False
        return res

    def action_decide_behall(self):
        if not self.decide_sender:
            raise UserError("Ange avsändarens e-postadress.")
        res = self._mail("/mail/waiting/decide", {
            "sender": self.decide_sender, "action": "BEHÅLL"})
        self.decide_sender = False
        return res

    def action_interview_start(self):
        if not self.interview_to:
            raise UserError("Ange mottagarens e-postadress.")
        return self._mail("/mail/interview/start", {
            "to":      self.interview_to,
            "subject": self.interview_subject or "Intervju",
            "context": self.interview_context or "",
        })

    def action_interview_stop(self):
        if not self.interview_to:
            raise UserError("Ange deltagarens e-postadress.")
        res = self._mail("/mail/interview/stop", {"participant": self.interview_to})
        self.interview_to = False
        return res

    # ── Hjälp ─────────────────────────────────────────────────────────────────

    def _reopen(self):
        return {
            "type":      "ir.actions.act_window",
            "res_model": self._name,
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "current",
        }
