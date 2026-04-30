from odoo import models, fields


class UapSource(models.Model):
    _name        = "uap.source"
    _description = "UAP — Källa"
    _order       = "name"
    _rec_name    = "name"

    source_id = fields.Char(
        string="Source ID",
        required=True,
        index=True,
        help="Unikt ID, t.ex. ufo-se_1974_vallentuna",
    )
    name = fields.Char(string="Name", required=True)
    source_type = fields.Selection(
        selection=[
            ("book",         "Book"),
            ("documentary",  "Documentary"),
            ("article",      "Article"),
            ("archive",      "Archive"),
            ("web",          "Web"),
            ("journalism",   "Journalism"),
            ("other",        "Other"),
        ],
        string="Type",
    )
    tier = fields.Selection(
        selection=[
            ("tier_1", "Tier 1 — Primary"),
            ("tier_2", "Tier 2 — Secondary"),
            ("tier_3", "Tier 3 — Tertiary"),
        ],
        string="Tier",
    )
    url = fields.Char(string="URL")
    published_date = fields.Date(string="Published Date")
    language = fields.Char(string="Language")
    encounter_ids = fields.Many2many(
        comodel_name="uap.encounter",
        relation="uap_encounter_source_rel",
        column1="source_id_col",
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
