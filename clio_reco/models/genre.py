from odoo import fields, models


class ClioRecoGenre(models.Model):
    _name = 'clio.reco.genre'
    _description = 'Rekommendation — Genre/Tagg'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer(default=0)

    item_ids = fields.Many2many('clio.reco.item', string='Items')
