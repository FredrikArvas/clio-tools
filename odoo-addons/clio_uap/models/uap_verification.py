from odoo import models, fields


class UapVerification(models.Model):
    _name        = "uap.verification"
    _description = "UAP — Verification Log"
    _order       = "change_date desc"
    _rec_name    = "name"

    name = fields.Char(string="Name", required=True)
    encounter_id = fields.Many2one(
        comodel_name="uap.encounter",
        string="Encounter",
        required=True,
        ondelete="cascade",
        index=True,
    )
    change_date = fields.Date(string="Change Date", required=True)
    changed_by = fields.Char(string="Changed By")
    field_name = fields.Char(string="Field")
    original_value = fields.Text(string="Original Value")
    updated_value = fields.Text(string="Updated Value")
    reason = fields.Text(string="Reason")
    source_link = fields.Char(string="Source Link")
    verification_status = fields.Selection(
        selection=[
            ("verified", "Verified"),
            ("pending",  "Pending"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="pending",
    )
