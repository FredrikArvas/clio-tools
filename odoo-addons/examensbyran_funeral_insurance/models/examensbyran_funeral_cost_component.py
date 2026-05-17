# -*- coding: utf-8 -*-
from odoo import fields, models


class ExamensbyranFuneralCostComponent(models.Model):
    _name = 'examensbyran.funeral.cost.component'
    _description = 'Begravningskostnadskomponent'
    _order = 'category, sequence, name'

    name = fields.Char(
        string='Komponent', required=True,
        help='T.ex. "Enkel kista", "Gravsten", "Blommor"')
    category = fields.Selection([
        ('ceremony', 'Ceremoni'),
        ('burial', 'Begravning/kremering'),
        ('coffin', 'Kista'),
        ('gravestone', 'Gravsten'),
        ('flowers', 'Blommor'),
        ('reception', 'Minnesstund'),
        ('transport', 'Transport'),
        ('admin', 'Administrativa avgifter'),
        ('other', 'Övrigt'),
    ], string='Kategori', required=True)

    sequence = fields.Integer(string='Sortering', default=10)

    cost_min = fields.Monetary(
        string='Lägsta kostnad (SEK)', currency_field='currency_id')
    cost_max = fields.Monetary(
        string='Högsta kostnad (SEK)', currency_field='currency_id')
    cost_typical = fields.Monetary(
        string='Typisk kostnad (SEK)', currency_field='currency_id',
        help='Medelpris som används i kalkyler')
    currency_id = fields.Many2one(
        'res.currency', string='Valuta',
        default=lambda self: self.env.ref('base.SEK'))

    description = fields.Text(string='Beskrivning')
    is_optional = fields.Boolean(
        string='Valfri', help='Om komponenten kan utelämnas')
    active = fields.Boolean(default=True)
