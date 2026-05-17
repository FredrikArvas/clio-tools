# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ExamensbyranFuneralAssessment(models.Model):
    _name = 'examensbyran.funeral.assessment'
    _description = 'Begravningsförsäkring — Självskattning'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'display_name'

    partner_id = fields.Many2one(
        'res.partner', string='Kontakt',
        ondelete='set null', index=True)

    has_home_insurance = fields.Boolean(string='Har hemförsäkring')
    home_insurance_provider = fields.Char(string='Hemförsäkringsbolag')

    has_life_insurance = fields.Boolean(string='Har livförsäkring')
    life_insurance_provider = fields.Char(string='Livförsäkringsbolag')
    life_insurance_amount = fields.Monetary(
        string='Livförsäkringsbelopp (SEK)', currency_field='currency_id')

    has_union_membership = fields.Boolean(string='Medlem i fackförbund')
    union_name = fields.Char(string='Fackförbund')

    has_funeral_insurance = fields.Boolean(
        string='Har särskild begravningsförsäkring')
    funeral_insurance_amount = fields.Monetary(
        string='Känt försäkringsbelopp (SEK)', currency_field='currency_id',
        help='Om användaren vet beloppet')

    preferred_funeral_type = fields.Selection([
        ('burial', 'Begravning'),
        ('cremation', 'Kremering'),
        ('unsure', 'Vet ej'),
    ], string='Önskad begravningsform', default='unsure')

    preferred_ceremony_size = fields.Selection([
        ('small', 'Liten (< 20 personer)'),
        ('medium', 'Mellan (20–50 personer)'),
        ('large', 'Stor (> 50 personer)'),
        ('unsure', 'Vet ej'),
    ], string='Förväntad ceremoni', default='unsure')

    estimated_cost_min = fields.Monetary(
        string='Beräknad kostnad (min)', currency_field='currency_id',
        readonly=True)
    estimated_cost_typical = fields.Monetary(
        string='Beräknad kostnad (typisk)', currency_field='currency_id',
        readonly=True)
    estimated_cost_max = fields.Monetary(
        string='Beräknad kostnad (max)', currency_field='currency_id',
        readonly=True)

    known_coverage = fields.Monetary(
        string='Känt försäkringsskydd', currency_field='currency_id',
        compute='_compute_known_coverage', store=True)
    coverage_gap = fields.Monetary(
        string='Potentiell brist', currency_field='currency_id',
        compute='_compute_coverage_gap', store=True)

    recommendation = fields.Html(
        string='Rekommendation', readonly=True,
        help='Genererad text med nästa steg')

    currency_id = fields.Many2one(
        'res.currency', string='Valuta',
        default=lambda self: self.env.ref('base.SEK'))
    state = fields.Selection([
        ('draft', 'Utkast'),
        ('completed', 'Genomförd'),
        ('followup', 'Intresseanmäld för uppföljning'),
    ], string='Status', default='draft', tracking=True)

    display_name = fields.Char(
        compute='_compute_display_name', store=True)

    wants_followup = fields.Boolean(string='Önskar uppföljning')
    followup_email = fields.Char(string='E-post för uppföljning')
    followup_phone = fields.Char(string='Telefon för uppföljning')
    followup_notes = fields.Text(string='Anteckningar från uppföljning')

    @api.depends('create_date', 'partner_id')
    def _compute_display_name(self):
        for rec in self:
            date_str = rec.create_date.strftime('%Y-%m-%d') if rec.create_date else '—'
            if rec.partner_id:
                rec.display_name = f'{rec.partner_id.name} — {date_str}'
            else:
                rec.display_name = f'Anonym skattning — {date_str}'

    @api.depends('life_insurance_amount', 'funeral_insurance_amount')
    def _compute_known_coverage(self):
        for rec in self:
            rec.known_coverage = (
                (rec.life_insurance_amount or 0) +
                (rec.funeral_insurance_amount or 0)
            )

    @api.depends('known_coverage', 'estimated_cost_typical')
    def _compute_coverage_gap(self):
        for rec in self:
            rec.coverage_gap = max(
                0, rec.estimated_cost_typical - rec.known_coverage)

    def action_generate_report(self):
        self.ensure_one()
        components = self.env['examensbyran.funeral.cost.component'].search(
            [('active', '=', True)])

        cost_min = sum(c.cost_min for c in components if not c.is_optional)
        cost_typical = sum(c.cost_typical for c in components if not c.is_optional)
        cost_max = sum(c.cost_max for c in components)

        if self.preferred_ceremony_size == 'large':
            cost_typical *= 1.3
            cost_max *= 1.5
        elif self.preferred_ceremony_size == 'small':
            cost_typical *= 0.8

        self.write({
            'estimated_cost_min': cost_min,
            'estimated_cost_typical': cost_typical,
            'estimated_cost_max': cost_max,
            'state': 'completed',
        })

        self._generate_recommendation_text()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Rapport genererad',
                'message': 'Din personliga begravningskostnadsrapport är klar.',
                'type': 'success',
                'sticky': False,
            },
        }

    def _generate_recommendation_text(self):
        self.ensure_one()
        gap = self.coverage_gap

        if gap == 0:
            status = (
                '<p style="color:green;font-weight:bold;">'
                '&#x2705; Ditt försäkringsskydd verkar täcka begravningskostnaden.'
                '</p>'
            )
            advice = (
                '<p>Kontrollera villkoren i dina befintliga försäkringar för att '
                'säkerställa att beloppet faktiskt utbetalas vid dödsfall.</p>'
            )
        elif gap < 10000:
            status = (
                '<p style="color:orange;font-weight:bold;">'
                '&#x26A0;&#xFE0F; Du kan ha en mindre brist i ditt försäkringsskydd.'
                '</p>'
            )
            advice = (
                f'<p>Beräknad brist: <strong>{int(gap):,} SEK</strong>. '
                f'Överväg att komplettera med ett begravningstillägg på din hemförsäkring.</p>'
            )
        else:
            status = (
                '<p style="color:red;font-weight:bold;">'
                '&#x274C; Du saknar troligen tillräckligt försäkringsskydd.'
                '</p>'
            )
            advice = (
                f'<p>Beräknad brist: <strong>{int(gap):,} SEK</strong>. '
                f'Kontakta ditt försäkringsbolag för en genomgång.</p>'
            )

        suggestions = '<h3>Nästa steg:</h3><ul>'

        if self.has_home_insurance and self.home_insurance_provider:
            suggestions += (
                f'<li>Kontakta <strong>{self.home_insurance_provider}</strong> '
                f'och fråga om begravningstillägg till din hemförsäkring.</li>'
            )
        if self.has_union_membership and self.union_name:
            suggestions += (
                f'<li>Kolla dina förmåner hos <strong>{self.union_name}</strong> '
                f'— många fackförbund inkluderar begravningshjälp.</li>'
            )
        if not self.has_funeral_insurance:
            suggestions += (
                '<li>Överväg att teckna en särskild begravningsförsäkring '
                'om du vill ha större kontroll över kostnaderna.</li>'
            )
        suggestions += (
            '<li>Dokumentera din önskan i ditt <strong>framtidsbrev</strong> '
            'så dina anhöriga vet hur du vill ha det.</li>'
        )
        suggestions += '</ul>'

        self.recommendation = status + advice + suggestions

    def action_request_followup(self):
        self.ensure_one()
        self.state = 'followup'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tack!',
                'message': 'Vi återkommer till dig inom 2 arbetsdagar.',
                'type': 'success',
                'sticky': False,
            },
        }
