"""
clio_tool_heartbeat.py
Heartbeat-post som varje clio-agent skriver efter körning.
Visas i clio_cockpit som samlad hälsostatus.
"""

import json
import logging
import urllib.error
import urllib.request

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

STATUS_SELECTION = [
    ("ok",      "OK"),
    ("warning", "Warning"),
    ("error",   "Error"),
]


class ClioToolHeartbeat(models.Model):
    _name        = "clio.tool.heartbeat"
    _description = "Clio — Agenthälsa"
    _order       = "last_run desc"
    _rec_name    = "tool_name"

    tool_name = fields.Char(
        string="Tool",
        required=True,
        index=True,
        help="Tekniskt namn, t.ex. 'clio-agent-job'.",
    )
    last_run = fields.Datetime(
        string="Last Run",
        required=True,
        copy=False,
    )
    status = fields.Selection(
        selection=STATUS_SELECTION,
        string="Status",
        required=True,
        default="ok",
    )
    items_processed = fields.Integer(
        string="Items Processed",
        default=0,
        help="Antal artiklar, poster eller objekt som behandlades.",
    )
    message = fields.Char(
        string="Message",
        help="Kort sammanfattning av körningen.",
    )

    # ── Computed ──────────────────────────────────────────────────────────────

    status_icon = fields.Char(
        string="",
        compute="_compute_status_icon",
        store=False,
    )

    def _compute_status_icon(self):
        icons = {"ok": "✅", "warning": "⚠️", "error": "❌"}
        for rec in self:
            rec.status_icon = icons.get(rec.status, "❓")

    # ── Business logic ────────────────────────────────────────────────────────

    def action_sync_heartbeat(self):
        base = self.env["ir.config_parameter"].sudo().get_param(
            "clio.service.url", default="http://172.18.0.1:7200"
        ).rstrip("/")

        def _fetch(path):
            req = urllib.request.Request(
                f"{base}{path}", method="GET",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read())
            except urllib.error.URLError as e:
                raise UserError(f"Kunde inte nå clio-service ({base}): {e.reason}")

        # Agentstatus
        agents_result = _fetch("/agents/status")
        for key, info in agents_result.get("agents", {}).items():
            status = "ok" if info.get("active") else "error"
            label  = info.get("label", key)
            msg    = info.get("status", "")
            if key == "rag" and info.get("active"):
                parts = []
                if info.get("books"): parts.append("böcker")
                if info.get("ncc"):   parts.append("NCC")
                if parts: msg += f" [{', '.join(parts)}]"
            self.record_heartbeat(self.env, label, status, 0, msg)

        # Docker
        docker_result = _fetch("/health/docker")
        for c in docker_result.get("containers", []):
            status = "ok" if c.get("running") else "error"
            self.record_heartbeat(
                self.env,
                f"docker:{c.get('name', '?')}",
                status, 0,
                c.get("status", ""),
            )

        return {"type": "ir.actions.client", "tag": "reload"}

    @classmethod
    def record_heartbeat(cls, env, tool_name: str, status: str,
                         items_processed: int = 0, message: str = "") -> None:
        """
        Upsert: uppdatera befintlig post för tool_name, eller skapa ny.
        Anropas från Python-backenden via XML-RPC.
        """
        Heartbeat = env["clio.tool.heartbeat"]
        existing = Heartbeat.search([("tool_name", "=", tool_name)], limit=1)
        vals = {
            "last_run":        fields.Datetime.now(),
            "status":          status,
            "items_processed": items_processed,
            "message":         message or "",
        }
        if existing:
            existing.write(vals)
            _logger.info("Heartbeat uppdaterad: %s → %s", tool_name, status)
        else:
            vals["tool_name"] = tool_name
            Heartbeat.create(vals)
            _logger.info("Heartbeat skapad: %s → %s", tool_name, status)
