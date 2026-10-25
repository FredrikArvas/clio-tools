from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RecoContext(models.Model):
    _name = 'clio.reco.context'
    _description = 'Betygssammanhang'
    _order = 'name'

    name = fields.Char(required=True)
    question = fields.Char()
    description = fields.Html(sanitize=True)
    scale_min = fields.Integer(default=1)
    scale_max = fields.Integer(default=5)
    scale_label_min = fields.Char()
    scale_label_max = fields.Char()
    is_sensitive = fields.Boolean(default=False)
    work_type_ids = fields.Many2many(
        'clio.media.work.type',
        string='Verkstyper',
    )
    rater_group_ids = fields.Many2many(
        'res.groups',
        string='Betygsättargrupper',
    )
    state = fields.Selection(
        [('nominated', 'Nominerat'), ('approved', 'Godkänt'), ('rejected', 'Avslaget')],
        default='nominated',
        required=True,
        string='Status',
    )
    nominated_by_id = fields.Many2one(
        'res.users',
        default=lambda self: self.env.user,
        string='Nominerad av',
    )

    @api.constrains('scale_min', 'scale_max')
    def _check_scale(self):
        for rec in self:
            if rec.scale_min >= rec.scale_max:
                raise ValidationError('Skalans minimum måste vara lägre än maximum.')

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})
