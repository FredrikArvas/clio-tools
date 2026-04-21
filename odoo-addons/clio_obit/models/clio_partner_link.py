"""
clio_partner_link.py
Enkel relationsmodell: en person → en annan person med en etikett.
"""

from odoo import models, fields


class ClioPartnerLink(models.Model):
    _name        = "clio.partner.link"
    _description = "Clio partnerrelation"

    from_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Från partner",
        required=True,
        ondelete="cascade",
    )
    to_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Person",
        required=True,
    )
    relation_label = fields.Char(
        string="Relation",
        help="T.ex. dotter, make, granne",
    )
