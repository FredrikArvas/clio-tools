from odoo import models, fields, api

SHELF_SELECTION = [
    ('A1', 'A1'), ('A2', 'A2'), ('A3', 'A3'), ('A4', 'A4'), ('A5', 'A5'), ('A6', 'A6'),
    ('B1', 'B1'), ('B2', 'B2'), ('B3', 'B3'), ('B4', 'B4'), ('B5', 'B5'), ('B6', 'B6'),
    ('C1', 'C1'), ('C2', 'C2'), ('C3', 'C3'), ('C4', 'C4'), ('C5', 'C5'), ('C6', 'C6'),
    ('W1', 'W1'), ('W2', 'W2'),
    ('Kok1', 'Kök1'), ('Kok2', 'Kök2'),
]


class LibraryBook(models.Model):
    _name = 'library.book'
    _description = 'Bok'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Titel', required=True)
    bok_id = fields.Char(string='BOK-ID', readonly=True, copy=False)
    author = fields.Char(string='Författare')
    author_last = fields.Char(string='Efternamn')
    author_first = fields.Char(string='Förnamn')
    isbn = fields.Char(string='ISBN')
    year = fields.Integer(string='År')
    publisher = fields.Char(string='Förlag')
    shelf = fields.Selection(SHELF_SELECTION, string='Hyllplats')
    language = fields.Selection([
        ('sv', 'Svenska'), ('en', 'Engelska'), ('de', 'Tyska'),
        ('no', 'Norska'), ('da', 'Danska'),
    ], string='Språk')
    format = fields.Selection([
        ('physical', 'Fysisk'), ('ebook', 'E-bok'), ('audio', 'Ljudbok'),
    ], string='Format')
    house = fields.Selection([
        ('FrUlleBo', 'FrUlleBo'),
        ('Stigmansgarden', 'Stigmansgården'),
        ('Ekshäradsgatan', 'Ekshäradsgatan'),
        ('Annat', 'Annat'),
    ], string='Hus')
    rating_ids = fields.One2many('library.rating', 'book_id', string='Betyg')
    avg_rating = fields.Float(string='Snittbetyg', compute='_compute_avg_rating', store=True)
    active = fields.Boolean(default=True)

    @api.depends('rating_ids.rating')
    def _compute_avg_rating(self):
        for book in self:
            ratings = book.rating_ids.mapped('rating')
            book.avg_rating = sum(ratings) / len(ratings) if ratings else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('bok_id'):
                vals['bok_id'] = self.env['ir.sequence'].next_by_code('library.book') or '/'
        return super().create(vals_list)
