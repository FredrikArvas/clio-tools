from odoo import models, fields


class SsfPayment(models.Model):
    _name = 'ssf.payment'
    _description = 'Startavgiftsbetalning (SSFTA)'
    _order = 'date desc'

    ssfta_id        = fields.Integer(string='SSFTA ID', index=True, readonly=True)
    organization_id = fields.Many2one(
        'res.partner', string='Förening',
        readonly=True, ondelete='set null', index=True,
    )
    event_id        = fields.Many2one(
        'ssf.event', string='Evenemang',
        readonly=True, ondelete='set null', index=True,
    )
    order_id        = fields.Char(string='Order-ID', readonly=True)
    date            = fields.Date(string='Datum', readonly=True)
    amount          = fields.Float(string='Belopp (kr)', readonly=True, digits=(12, 2))
    status          = fields.Char(string='Status', readonly=True)
    entry_ids       = fields.One2many(
        'ssf.payment.entry', 'payment_id', string='Anmälningar',
    )
