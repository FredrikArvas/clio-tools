from odoo import models, fields, api


class SsfFeeReport(models.Model):
    _name = 'ssf.fee.report'
    _description = 'LOK-stödsrapport'
    _order = 'report_date desc'

    ssfta_id       = fields.Integer(string='SSFTA ID', index=True, readonly=True)
    competition_id = fields.Many2one(
        'ssf.competition', string='Tävling',
        readonly=True, ondelete='set null', index=True,
    )
    reference      = fields.Char(string='IOL-referens', readonly=True)
    report_date    = fields.Date(string='Rapportdatum', readonly=True)
    report_amount  = fields.Float(string='Rapporterat (kr)', readonly=True, digits=(12, 2))
    paid_date      = fields.Date(string='Utbetalt datum', readonly=True)
    paid_amount    = fields.Float(string='Utbetalt (kr)', readonly=True, digits=(12, 2))
    claim          = fields.Float(
        string='Utestående (kr)', compute='_compute_claim', store=True, digits=(12, 2),
    )
    value_ids      = fields.One2many('ssf.fee.report.value', 'fee_report_id', string='Per distrikt')

    @api.depends('report_amount', 'paid_amount')
    def _compute_claim(self):
        for r in self:
            r.claim = (r.report_amount or 0.0) - (r.paid_amount or 0.0)
