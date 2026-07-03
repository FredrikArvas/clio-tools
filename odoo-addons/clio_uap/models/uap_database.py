from odoo import models, fields


class UapDatabase(models.Model):
    _name        = "uap.database"
    _description = "UAP — Organisation Database"
    _order       = "name"
    _rec_name    = "name"

    name = fields.Char(string="Database Name", required=True)
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Owner Organisation",
        index=True,
        ondelete="restrict",
    )
    db_type = fields.Selection(
        selection=[
            ("reporting", "Reporting Database"),
            ("archive",   "Historical Archive"),
            ("library",   "Document Library"),
            ("registry",  "Official Registry"),
            ("other",     "Other"),
        ],
        string="Type",
        default="reporting",
    )
    db_url = fields.Char(string="Database URL")
    description = fields.Text(string="Description")
    language = fields.Selection(
        selection=[
            ("en",    "English"),
            ("sv",    "Swedish"),
            ("fr",    "French"),
            ("de",    "German"),
            ("es",    "Spanish"),
            ("pt",    "Portuguese"),
            ("other", "Other"),
        ],
        string="Primary Language",
    )
    record_count = fields.Integer(string="Reported Record Count")
    last_synced  = fields.Datetime(string="Last Synced")

    encounter_ids = fields.One2many(
        comodel_name="uap.encounter",
        inverse_name="database_id",
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
