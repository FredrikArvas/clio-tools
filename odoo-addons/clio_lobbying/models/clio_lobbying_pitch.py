"""
clio_lobbying_pitch.py
Ett enskilt pitch-utkast riktat till en journalist för en specifik händelse.
Skapas av pipeline (pitcher.py) och granskas/skickas manuellt i Odoo.
"""

from __future__ import annotations

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ClioLobbyingPitch(models.Model):
    _name        = "clio.lobbying.pitch"
    _description = "Clio Lobbying — Pitch"
    _order       = "create_date desc"
    _rec_name    = "display_name"

    # ── Relationer ───────────────────────────────────────────────────────────

    event_id = fields.Many2one(
        comodel_name="clio.lobbying.event",
        string="Händelse",
        required=True,
        ondelete="cascade",
        index=True,
    )
    journalist_id = fields.Many2one(
        comodel_name="clio.lobbying.journalist",
        string="Journalist",
        required=True,
        ondelete="restrict",
        index=True,
    )

    display_name = fields.Char(
        string="Pitch",
        compute="_compute_display_name",
        store=True,
    )

    def _compute_display_name(self):
        for rec in self:
            j = rec.journalist_id.name if rec.journalist_id else "?"
            e = rec.event_id.name if rec.event_id else "?"
            rec.display_name = f"{j} — {e}"

    # ── Pitch-innehåll ───────────────────────────────────────────────────────

    subject = fields.Char(
        string="Ämnesrad",
        help="Extraheras automatiskt ur pitch_text. Kan redigeras manuellt.",
    )
    pitch_text = fields.Text(
        string="Pitch-text",
        help="Genererat utkast. Granska och justera innan sändning.",
    )
    match_reason = fields.Char(
        string="Matchningsgrund",
        help="Varför Claude matchade denna journalist till händelsen.",
        readonly=True,
    )

    # ── Tillstånd ────────────────────────────────────────────────────────────

    state = fields.Selection(
        selection=[
            ("draft",      "Utkast"),
            ("approved",   "Godkänd"),
            ("sent",       "Skickad"),
            ("responded",  "Fått svar"),
            ("dismissed",  "Avvisad"),
        ],
        string="Status",
        default="draft",
        index=True,
    )

    # ── Uppföljning ──────────────────────────────────────────────────────────

    sent_at = fields.Datetime(string="Skickad", readonly=True)
    response_notes = fields.Text(
        string="Svarsnot",
        help="Anteckna journalistens svar eller uppföljning.",
    )

    # ── Hjälpfält (denormaliserade för listor) ───────────────────────────────

    journalist_email = fields.Char(
        related="journalist_id.email",
        string="E-post",
        readonly=True,
        store=True,
    )
    journalist_publication = fields.Char(
        related="journalist_id.publication",
        string="Publikation",
        readonly=True,
        store=True,
    )

    # ── Åtgärder ─────────────────────────────────────────────────────────────

    def action_approve(self):
        """Markerar pitchen som godkänd för sändning."""
        self.write({"state": "approved"})

    def action_mark_sent(self):
        """Markerar pitchen som skickad (manuell sändning utanför Odoo)."""
        self.write({"state": "sent", "sent_at": fields.Datetime.now()})

    def action_mark_responded(self):
        """Journalisten har svarat."""
        self.write({"state": "responded"})

    def action_dismiss(self):
        """Avvisar pitchen utan att skicka."""
        self.write({"state": "dismissed"})

    def action_reset_draft(self):
        """Återställer till utkast för ny redigering."""
        self.write({"state": "draft"})
