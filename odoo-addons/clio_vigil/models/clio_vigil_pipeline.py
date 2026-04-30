"""
clio_vigil_pipeline.py
Kontrollpanel för manuell styrning av clio-vigil pipeline.
Skriver en trigger-fil som systemd clio-vigil-trigger.path plockar upp.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_TRIGGER_FILE = "/mnt/clio-tools/clio-vigil/data/.vigil_trigger"
_STATUS_FILE  = "/mnt/clio-tools/clio-vigil/data/.vigil_status"

_STEP_LABELS = {
    "run":        "Samla in",
    "transcribe": "Transkribera",
    "summarize":  "Summera",
    "index":      "Indexera",
    "digest":     "Digest-mail",
    "full":       "Full pipeline",
    "seed":       "Importera källor",
    "recompute":  "Räkna om prioriteter",
}


class ClioVigilPipeline(models.TransientModel):
    _name        = "clio.vigil.pipeline"
    _description = "Clio Vigil — Pipelinestyrning"

    # ── Heartbeat ────────────────────────────────────────────────────────────

    heartbeat_status   = fields.Selection(
        selection = [("ok", "OK"), ("warning", "Varning"), ("error", "Fel"), ("unknown", "Okänd")],
        string    = "Status",
        compute   = "_compute_heartbeat",
        default   = "unknown",
    )
    heartbeat_last_run = fields.Datetime(string="Senaste körning",  compute="_compute_heartbeat")
    heartbeat_message  = fields.Char(   string="Meddelande",        compute="_compute_heartbeat")

    # ── Senaste trigger ───────────────────────────────────────────────────────

    last_step      = fields.Char(    string="Senaste steg",   compute="_compute_trigger_status")
    last_status    = fields.Selection(
        selection = [("running", "Kör"), ("done", "Klar"), ("error", "Fel"), ("unknown", "Okänd")],
        string    = "Senaste resultat",
        compute   = "_compute_trigger_status",
        default   = "unknown",
    )
    last_triggered = fields.Char(string="Triggrad av",     compute="_compute_trigger_status")
    last_completed = fields.Datetime(string="Avslutad",    compute="_compute_trigger_status")

    @api.depends()
    def _compute_heartbeat(self):
        for rec in self:
            hb = self.env["clio.tool.heartbeat"].search(
                [("tool_name", "=", "clio-vigil")], limit=1
            )
            if hb:
                rec.heartbeat_status   = hb.status or "unknown"
                rec.heartbeat_last_run = hb.last_run
                rec.heartbeat_message  = hb.message or ""
            else:
                rec.heartbeat_status   = "unknown"
                rec.heartbeat_last_run = False
                rec.heartbeat_message  = "Ingen heartbeat registrerad ännu"

    @api.depends()
    def _compute_trigger_status(self):
        for rec in self:
            try:
                data = json.loads(Path(_STATUS_FILE).read_text())
                rec.last_step      = _STEP_LABELS.get(data.get("step", ""), data.get("step", "?"))
                rec.last_status    = data.get("status", "unknown")
                rec.last_triggered = data.get("triggered_by", "?")
                completed = data.get("completed_at") or data.get("started_at")
                rec.last_completed = completed[:19].replace("T", " ") if completed else False
            except Exception:
                rec.last_step      = ""
                rec.last_status    = "unknown"
                rec.last_triggered = ""
                rec.last_completed = False

    # ── Trigger-hjälpmetoder ─────────────────────────────────────────────────

    def _write_trigger(self, step: str) -> None:
        try:
            os.makedirs(os.path.dirname(_TRIGGER_FILE), exist_ok=True)
            payload = {
                "step":         step,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "triggered_by": self.env.user.login,
            }
            Path(_TRIGGER_FILE).write_text(json.dumps(payload))
            _logger.info("clio-vigil trigger skriven: %s av %s", step, self.env.user.login)
        except Exception as exc:
            _logger.error("Kunde inte skriva trigger-fil: %s", exc)
            raise

    def _notify(self, step: str):
        label = _STEP_LABELS.get(step, step)
        return {
            "type": "ir.actions.client",
            "tag":  "display_notification",
            "params": {
                "title":   f"Pipeline triggrad: {label}",
                "message": "Startar inom några sekunder via systemd.",
                "type":    "success",
                "sticky":  False,
            },
        }

    # ── Åtgärdsknappar ───────────────────────────────────────────────────────

    def action_run(self):
        self._write_trigger("run")
        return self._notify("run")

    def action_transcribe(self):
        self._write_trigger("transcribe")
        return self._notify("transcribe")

    def action_summarize(self):
        self._write_trigger("summarize")
        return self._notify("summarize")

    def action_index(self):
        self._write_trigger("index")
        return self._notify("index")

    def action_digest(self):
        self._write_trigger("digest")
        return self._notify("digest")

    def action_full(self):
        self._write_trigger("full")
        return self._notify("full")

    def action_seed(self):
        self._write_trigger("seed")
        return self._notify("seed")

    def action_recompute(self):
        self._write_trigger("recompute")
        return self._notify("recompute")
