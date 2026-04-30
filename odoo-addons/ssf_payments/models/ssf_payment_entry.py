from odoo import models, fields


class SsfPaymentEntry(models.Model):
    _name = 'ssf.payment.entry'
    _description = 'Betalning per anmälan'
    _order = 'payment_id'

    ssfta_id   = fields.Integer(string='SSFTA ID', index=True, readonly=True)
    payment_id = fields.Many2one(
        'ssf.payment', required=True, ondelete='cascade', index=True,
    )
    entry_id   = fields.Many2one(
        'ssf.entry', string='Anmälan',
        readonly=True, ondelete='set null',
    )
    team_entry = fields.Integer(string='Laganmälan SSFTA-ID', readonly=True)
