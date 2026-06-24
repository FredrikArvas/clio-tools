"""
clio_lobbying_event.py
En nyhetshändelse som triggar en pitch-kampanj.
Trigger-knappen skriver en JSON-fil som systemd clio-lobbying-trigger.path plockar upp.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_LOBBYING_TRIGGER = "/mnt/clio-tools/clio-vigil/data/.lobbying_trigger"
_LOBBYING_STATUS  = "/mnt/clio-tools/clio-vigil/data/.lobbying_status"


class ClioLobbyingEvent(models.Model):
    _name        = "clio.lobbying.event"
    _description = "Clio Lobbying — Händelse"
    _order       = "create_date desc"
    _rec_name    = "name"

    # ── Grunddata ────────────────────────────────────────────────────────────

    name = fields.Char(
        string="Händelse",
        required=True,
        help="Kort rubrik för händelsen, t.ex. 'Pentagon UAP-rapport Q3 2026'.",
    )
    event_text = fields.Text(
        string="Beskrivning",
        required=True,
        help="Detaljerad beskrivning som används som underlag för pitch-generering.",
    )
    domain = fields.Selection(
        selection=[("ufo", "UFO/UAP"), ("ai", "AI-modeller")],
        string="Domän",
        index=True,
    )
    source_url = fields.Char(
        string="Källlänk",
        help="URL till nyheten eller pressmeddelandet.",
    )

    # ── Tillstånd ────────────────────────────────────────────────────────────

    state = fields.Selection(
        selection=[
            ("draft",    "Utkast"),
            ("pitching", "Genererar pitchar"),
            ("review",   "Granskning"),
            ("closed",   "Avslutad"),
        ],
        string="Status",
        default="draft",
        index=True,
    )

    # ── Pitch-statistik ──────────────────────────────────────────────────────

    pitch_ids = fields.One2many(
        comodel_name="clio.lobbying.pitch",
        inverse_name="event_id",
        string="Pitchar",
    )
    pitch_count = fields.Integer(
        string="Pitchar",
        compute="_compute_pitch_counts",
    )
    sent_count = fields.Integer(
        string="Skickade",
        compute="_compute_pitch_counts",
    )

    @api.depends("pitch_ids.state")
    def _compute_pitch_counts(self):
        for rec in self:
            rec.pitch_count = len(rec.pitch_ids)
            rec.sent_count  = len(rec.pitch_ids.filtered(
                lambda p: p.state in ("sent", "responded")
            ))

    # ── Trigger-metadata ─────────────────────────────────────────────────────

    triggered_at = fields.Datetime(
        string="Senast triggrad",
        readonly=True,
    )
    triggered_by = fields.Char(
        string="Triggrad av",
        readonly=True,
    )
    trigger_status = fields.Selection(
        selection=[
            ("idle",    "Väntar"),
            ("running", "Kör"),
            ("done",    "Klar"),
            ("error",   "Fel"),
        ],
        string="Pipeline-status",
        compute="_compute_trigger_status",
    )

    @api.depends()
    def _compute_trigger_status(self):
        for rec in self:
            try:
                data = json.loads(Path(_LOBBYING_STATUS).read_text())
                status = data.get("status", "idle")
                event_id = data.get("event_odoo_id")
                if event_id == rec.id:
                    rec.trigger_status = status
                else:
                    rec.trigger_status = "idle"
            except Exception:
                rec.trigger_status = "idle"

    # ── Åtgärder ─────────────────────────────────────────────────────────────

    def action_generate_pitches(self):
        """Triggar pitch-generering via systemd. Skriver lobbying trigger-fil."""
        self.ensure_one()
        try:
            os.makedirs(os.path.dirname(_LOBBYING_TRIGGER), exist_ok=True)
            payload = {
                "action":        "pitch",
                "event_odoo_id": self.id,
                "event_text":    self.event_text,
                "domain":        self.domain or "",
                "triggered_at":  datetime.now(timezone.utc).isoformat(),
                "triggered_by":  self.env.user.login,
            }
            Path(_LOBBYING_TRIGGER).write_text(json.dumps(payload, ensure_ascii=False))
            self.write({
                "state":        "pitching",
                "triggered_at": fields.Datetime.now(),
                "triggered_by": self.env.user.login,
            })
            _logger.info("Lobbying trigger skriven: event %d av %s", self.id, self.env.user.login)
        except Exception as exc:
            _logger.error("Kunde inte skriva lobbying trigger: %s", exc)
            raise

        return {
            "type": "ir.actions.client",
            "tag":  "display_notification",
            "params": {
                "title":   "Pitch-generering triggrad",
                "message": "Startar inom några sekunder. Pitchar dyker upp under Pitch-kö.",
                "type":    "success",
                "sticky":  False,
            },
        }

    def action_extract_journalists(self):
        """Triggar byline-extraktion för domänen."""
        self.ensure_one()
        try:
            os.makedirs(os.path.dirname(_LOBBYING_TRIGGER), exist_ok=True)
            payload = {
                "action":       "extract_journalists",
                "domain":       self.domain or "",
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "triggered_by": self.env.user.login,
            }
            Path(_LOBBYING_TRIGGER).write_text(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            _logger.error("Kunde inte skriva trigger för journalist-extraktion: %s", exc)
            raise

        return {
            "type": "ir.actions.client",
            "tag":  "display_notification",
            "params": {
                "title":   "Journalist-extraktion triggrad",
                "message": "Extraherar bylines och bygger profiler i bakgrunden.",
                "type":    "info",
                "sticky":  False,
            },
        }

    def action_mark_review(self):
        self.write({"state": "review"})

    def action_close(self):
        self.write({"state": "closed"})

    def action_reopen(self):
        self.write({"state": "draft"})
