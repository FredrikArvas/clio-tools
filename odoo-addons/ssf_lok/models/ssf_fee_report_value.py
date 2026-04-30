from odoo import models, fields


class SsfFeeReportValue(models.Model):
    _name = 'ssf.fee.report.value'
    _description = 'LOK-rapport per distrikt'
    _order = 'competitors desc'

    ssfta_id      = fields.Integer(string='SSFTA ID', index=True, readonly=True)
    fee_report_id = fields.Many2one(
        'ssf.fee.report', required=True, ondelete='cascade', index=True,
    )
    district_id   = fields.Many2one(
        'res.partner', string='Distrikt', readonly=True, ondelete='set null',
    )
    competitors   = fields.Integer(string='Deltagare', readonly=True)
