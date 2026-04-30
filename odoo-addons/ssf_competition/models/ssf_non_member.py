from odoo import models, fields, api


class SsfNonMember(models.Model):
    _name = 'ssf.non.member'
    _description = 'Tävlingsdeltagare utan RF-medlemskap'
    _rec_name = 'name'
    _order = 'lastname, firstname'

    ssfta_id    = fields.Integer(string='SSFTA ID', index=True, readonly=True)
    firstname   = fields.Char(string='Förnamn', readonly=True)
    lastname    = fields.Char(string='Efternamn', readonly=True)
    name        = fields.Char(
        string='Namn', compute='_compute_name', store=True,
    )
    gender      = fields.Selection(
        [('M', 'Man'), ('F', 'Kvinna'), ('X', 'Annat')],
        string='Kön', readonly=True,
    )
    birthdate   = fields.Date(string='Födelsedag', readonly=True)
    nationality = fields.Char(string='Nationalitet', readonly=True)
    co_address  = fields.Char(string='c/o adress', readonly=True)

    @api.depends('firstname', 'lastname')
    def _compute_name(self):
        for r in self:
            r.name = ' '.join(filter(None, [r.firstname, r.lastname]))
