"""
res_partner.py
Utökar res.partner med dödsannonsbevakningsfält.
"""

from odoo import models, fields


class ResPartner(models.Model):
    _inherit = "res.partner"

    clio_obit_watch = fields.Boolean(
        string="Bevaka dödsannonser",
        default=False,
    )
    clio_obit_priority = fields.Selection(
        selection=[
            ("viktig",       "Viktig — direkt notis"),
            ("normal",       "Normal — daglig digest"),
            ("bra_att_veta", "Bra att veta"),
        ],
        string="Prioritet",
        default="normal",
    )
    clio_family_role = fields.Char(
        string="Familjeroll",
        help="T.ex. farfar, faster, granne",
    )
    clio_link_ids = fields.One2many(
        comodel_name="clio.partner.link",
        inverse_name="from_partner_id",
        string="Familjerelationer",
    )
