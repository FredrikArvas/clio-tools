from odoo import fields, models


class SsfIolRole(models.Model):
    _name        = 'ssf.iol.role'
    _description = 'IOL-roll (person i organisation)'
    _rec_name    = 'role_name'
    _order       = 'person_id, role_name'

    person_id       = fields.Many2one(
        'res.partner', string='Person',
        required=True, ondelete='cascade', index=True,
    )
    organization_id = fields.Many2one(
        'res.partner', string='Organisation',
        required=True, ondelete='cascade', index=True,
    )
    role_name = fields.Char(string='Roll', required=True, index=True)

    _sql_constraints = [
        ('unique_iol', 'UNIQUE(person_id, organization_id, role_name)',
         'Kombinationen person + organisation + roll finns redan'),
    ]
