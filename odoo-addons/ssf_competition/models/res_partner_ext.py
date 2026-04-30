from odoo import models, fields


class ResPartnerExt(models.Model):
    _inherit = 'res.partner'

    sector_ids = fields.Many2many(
        'ssf.sector', 'ssf_person_sector', 'person_id', 'sector_id',
        string='Grenar', readonly=True,
    )
