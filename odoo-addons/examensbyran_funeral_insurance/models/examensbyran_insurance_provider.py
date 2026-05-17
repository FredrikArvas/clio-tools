# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ExamensbyranInsuranceProvider(models.Model):
    _name = 'examensbyran.insurance.provider'
    _description = 'Försäkringsaktör'
    _order = 'name'

    name = fields.Char(string='Namn', required=True, index=True)
    provider_type = fields.Selection([
        ('insurance_company', 'Försäkringsbolag'),
        ('union', 'Fackförbund'),
        ('bank', 'Bank'),
        ('other', 'Annat'),
    ], string='Typ', required=True, default='insurance_company')

    website = fields.Char(string='Webbplats')
    phone = fields.Char(string='Telefon')
    email = fields.Char(string='E-post')

    logo = fields.Binary(string='Logotyp')
    description = fields.Html(string='Beskrivning')
    notes = fields.Text(string='Interna anteckningar')

    product_ids = fields.One2many(
        'examensbyran.insurance.product', 'provider_id', string='Produkter')
    product_count = fields.Integer(
        string='Antal produkter', compute='_compute_product_count')

    active = fields.Boolean(default=True)

    @api.depends('product_ids')
    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_ids)

    def action_view_products(self):
        self.ensure_one()
        return {
            'name': f'Produkter — {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'examensbyran.insurance.product',
            'view_mode': 'list,form',
            'domain': [('provider_id', '=', self.id)],
            'context': {'default_provider_id': self.id},
        }
