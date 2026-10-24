from odoo import api, fields, models


class ClioRecoItem(models.Model):
    _name = 'clio.reco.item'
    _description = 'Rekommendation'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'website.published.mixin']
    _order = 'name'

    ITEM_TYPE_SELECTION = [
        ('book', 'Bok'),
        ('film', 'Film'),
        ('link', 'Länk'),
    ]

    name = fields.Char(required=True, tracking=True)
    item_type = fields.Selection(ITEM_TYPE_SELECTION, required=True, default='book', tracking=True)
    url = fields.Char(string='URL')
    image_1920 = fields.Image('Omslagsbild', max_width=1920, max_height=1920)
    description = fields.Html(string='Beskrivning', sanitize=True)
    author = fields.Char(string='Upphovsperson')
    year = fields.Integer(string='År')
    genre_ids = fields.Many2many('clio.reco.genre', string='Genrer/Taggar')

    # Bok-specifikt
    isbn = fields.Char(string='ISBN', help='Används för bokökning')

    # Film-specifikt
    tmdb_id = fields.Integer(string='TMDB ID', help='The Movie Database ID')

    # Länk-specifikt
    domain = fields.Char(
        string='Domän',
        compute='_compute_domain',
        store=True,
        help='Extraheras automatiskt från URL',
    )

    @api.depends('url')
    def _compute_domain(self):
        for rec in self:
            if rec.url and rec.item_type == 'link':
                try:
                    from urllib.parse import urlparse
                    rec.domain = urlparse(rec.url).netloc or False
                except Exception:
                    rec.domain = False
            else:
                rec.domain = False

    def _default_website_meta(self):
        res = super()._default_website_meta()
        res['default_opengraph']['og:description'] = self.description or ''
        return res
