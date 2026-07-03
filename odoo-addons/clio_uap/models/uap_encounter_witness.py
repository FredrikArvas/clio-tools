from odoo import models, fields


class UapEncounterWitness(models.Model):
    _name        = "uap.encounter.witness"
    _description = "UAP — Encounter Witness"
    _order       = "encounter_id, credibility"
    _rec_name    = "partner_id"

    encounter_id = fields.Many2one(
        comodel_name="uap.encounter",
        string="Encounter",
        required=True,
        ondelete="cascade",
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Witness",
        required=True,
        ondelete="restrict",
    )
    witness_type = fields.Selection(
        selection=[
            ("military",   "Military"),
            ("civilian",   "Civilian"),
            ("pilot",      "Pilot"),
            ("researcher", "Researcher"),
            ("official",   "Official"),
            ("other",      "Other"),
        ],
        string="Type",
    )
    credibility = fields.Selection(
        selection=[
            ("tier_1", "Tier 1 — High"),
            ("tier_2", "Tier 2 — Medium"),
            ("tier_3", "Tier 3 — Low"),
        ],
        string="Credibility",
    )
    role = fields.Selection(
        selection=[
            ("primary",       "Primary Witness"),
            ("supporting",    "Supporting Witness"),
            ("corroborating", "Corroborating"),
        ],
        string="Role",
        default="primary",
    )
    notes = fields.Text(string="Notes")
