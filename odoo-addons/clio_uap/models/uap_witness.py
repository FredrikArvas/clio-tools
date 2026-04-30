from odoo import models, fields


class UapWitness(models.Model):
    _name        = "uap.witness"
    _description = "UAP — Vittne"
    _order       = "name"
    _rec_name    = "name"

    name = fields.Char(string="Name", required=True)
    witness_type = fields.Selection(
        selection=[
            ("military",    "Military"),
            ("civilian",    "Civilian"),
            ("pilot",       "Pilot"),
            ("researcher",  "Researcher"),
            ("official",    "Official"),
            ("other",       "Other"),
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
    status = fields.Char(string="Status")
    url = fields.Char(string="URL")
    language = fields.Char(string="Language")
    encounter_ids = fields.Many2many(
        comodel_name="uap.encounter",
        relation="uap_encounter_witness_rel",
        column1="witness_id_col",
        column2="encounter_id_col",
        string="Encounters",
    )
    encounter_count = fields.Integer(
        string="# Encounters",
        compute="_compute_encounter_count",
        store=False,
    )

    def _compute_encounter_count(self):
        for rec in self:
            rec.encounter_count = len(rec.encounter_ids)
