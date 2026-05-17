from odoo import models, fields


class LibraryRating(models.Model):
    _name = 'library.rating'
    _description = 'Bokbetyg'
    _order = 'book_id, user_id'

    book_id = fields.Many2one(
        'library.book', string='Bok', required=True, ondelete='cascade'
    )
    user_id = fields.Many2one('res.users', string='Person', required=True)
    rating = fields.Integer(string='Betyg', default=3)
    notes = fields.Text(string='Anteckning')
    date_read = fields.Date(string='Läst datum')

    _unique_book_user = models.Constraint(
        'UNIQUE(book_id, user_id)',
        'En person kan bara betygsätta en bok en gång.'
    )
