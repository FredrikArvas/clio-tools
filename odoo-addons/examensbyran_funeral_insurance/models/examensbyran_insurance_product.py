# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ExamensbyranInsuranceProduct(models.Model):
    _name = 'examensbyran.insurance.product'
    _description = 'Försäkringsprodukt'
    _order = 'provider_id, name'

    provider_id = fields.Many2one(
        'examensbyran.insurance.provider', string='Aktör',
        required=True, ondelete='cascade', index=True)

    name = fields.Char(
        string='Produktnamn', required=True,
        help='T.ex. "Begravningsförsäkring", "Livförsäkring med begravningstillägg"')
    product_type = fields.Selection([
        ('funeral_specific', 'Ren begravningsförsäkring'),
        ('home_addon', 'Tillägg till hemförsäkring'),
        ('life_addon', 'Tillägg till livförsäkring'),
        ('union_benefit', 'Fackförbundsförmån'),
        ('other', 'Annat'),
    ], string='Produkttyp', required=True)

    coverage_amount = fields.Monetary(
        string='Täckningsbelopp (SEK)', currency_field='currency_id',
        help='Utbetalning vid dödsfall')
    currency_id = fields.Many2one(
        'res.currency', string='Valuta',
        default=lambda self: self.env.ref('base.SEK'))

    premium_amount = fields.Monetary(
        string='Premie (SEK/år)', currency_field='currency_id')
    premium_frequency = fields.Selection([
        ('monthly', 'Månadsvis'),
        ('yearly', 'Årsvis'),
        ('once', 'Engångsbetalning'),
    ], string='Premiefrekvens', default='yearly')

    age_min = fields.Integer(string='Minimiålder', help='Lägsta ålder för tecknande')
    age_max = fields.Integer(string='Maxålder', help='Högsta ålder för tecknande')
    requires_membership = fields.Boolean(
        string='Kräver medlemskap',
        help='T.ex. fackförbund eller försäkringsbolag')
    membership_info = fields.Text(string='Medlemskapskrav')

    url = fields.Char(string='Produktlänk', help='URL till produktsida')
    description = fields.Html(string='Beskrivning')
    includes = fields.Text(string='Vad som ingår')
    excludes = fields.Text(string='Vad som INTE ingår')

    recommendation_score = fields.Integer(
        string='Rekommendationspoäng',
        help='1-10, används för sortering i jämförelsetabell')

    active = fields.Boolean(default=True)
    last_updated = fields.Date(
        string='Senast uppdaterad', default=fields.Date.today)

    display_name = fields.Char(
        compute='_compute_display_name', store=True)

    @api.depends('provider_id.name', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.provider_id.name} — {rec.name}'
