from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    ssfta_managed_partner_id = fields.Many2one(
        "res.partner",
        string="SSFTA-hanterad organisation",
        help="SDF eller förening som användaren administrerar i SSFTA.",
        ondelete="set null",
    )
