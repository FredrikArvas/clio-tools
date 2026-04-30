"""
clio_vigil_wizard.py
Wizard för att flytta markerade bevakningsobjekt till ett nytt tillstånd.
Öppnas via Actions-knappen i listvyn.
"""

from __future__ import annotations

from odoo import fields, models


class ClioVigilSetStateWizard(models.TransientModel):
    _name        = "clio.vigil.set.state.wizard"
    _description = "Clio Vigil — Ändra tillstånd"

    item_ids = fields.Many2many(
        "clio.vigil.item",
        string = "Objekt",
    )
    item_count = fields.Integer(
        string  = "Antal objekt",
        compute = "_compute_item_count",
    )
    new_state = fields.Selection(
        selection = [
            ("discovered",   "Hittad"),
            ("filtered_in",  "Passerade filter"),
            ("filtered_out", "Filtrerades bort"),
            ("queued",       "I kö"),
            ("transcribed",  "Transkriberad"),
            ("indexed",      "Indexerad"),
            ("notified",     "Skickad i digest"),
        ],
        string   = "Nytt tillstånd",
        required = True,
    )

    def _compute_item_count(self):
        for rec in self:
            rec.item_count = len(rec.item_ids)

    def action_apply(self):
        """Sätter new_state på alla valda objekt."""
        self.ensure_one()
        self.item_ids.write({"state": self.new_state})
        return {"type": "ir.actions.act_window_close"}
