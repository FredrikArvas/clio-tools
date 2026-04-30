from odoo import models, fields


class ResPartnerExt(models.Model):
    _inherit = 'res.partner'

    sector_ids = fields.Many2many(
        'ssf.sector', 'ssf_person_sector', 'person_id', 'sector_id',
        string='Grenar', readonly=True,
    )
    iol_role_ids = fields.One2many(
        'ssf.iol.role', 'person_id', string='IOL-roller (person)',
        readonly=True,
    )
    iol_org_role_ids = fields.One2many(
        'ssf.iol.role', 'organization_id', string='IOL-roller (organisation)',
        readonly=True,
    )
