"""
clio_tool_heartbeat.py
Heartbeat-post som varje clio-agent skriver efter körning.
Visas i clio_cockpit som samlad hälsostatus.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

STATUS_SELECTION = [
    ("ok",      "OK"),
    ("warning", "Varning"),
    ("error",   "Fel"),
]


class ClioToolHeartbeat(models.Model):
    _name        = "clio.tool.heartbeat"
    _description = "Clio — Agenthälsa"
    _order       = "last_run desc"
    _rec_name    = "tool_name"

    tool_name = fields.Char(
        string="Verktyg",
        required=True,
        index=True,
        help="Tekniskt namn, t.ex. 'clio-agent-job'.",
    )
    last_run = fields.Datetime(
        string="Senaste körning",
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
        string="Bearbetade objekt",
        default=0,
        help="Antal artiklar, poster eller objekt som behandlades.",
    )
    message = fields.Char(
        string="Meddelande",
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
