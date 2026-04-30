from odoo import models, fields
from .ssf_event import GEO_SCOPE


class SsfCup(models.Model):
    _name = 'ssf.cup'
    _description = 'Tävlingsserie'
    _order = 'name'

    ssfta_id           = fields.Integer(string='SSFTA ID', index=True, readonly=True)
    name               = fields.Char(string='Namn', required=True, readonly=True)
    sector_id          = fields.Many2one('ssf.sector', string='Gren', readonly=True, ondelete='set null')
    season_id          = fields.Many2one('ssf.season', string='Säsong', readonly=True, ondelete='set null')
    geographical_scope = fields.Selection(GEO_SCOPE, string='Räckvidd', readonly=True)
    organizer_id       = fields.Many2one('res.partner', string='Arrangör', readonly=True, ondelete='set null')
    email              = fields.Char(string='E-post', readonly=True)
    description        = fields.Text(string='Beskrivning', readonly=True)
    event_ids          = fields.One2many('ssf.event', 'cup_id', string='Evenemang')
