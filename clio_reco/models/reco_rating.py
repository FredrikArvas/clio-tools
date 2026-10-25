from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RecoRating(models.Model):
    _name = 'clio.reco.rating'
    _description = 'Betyg'
    _order = 'date desc'

    work_id = fields.Many2one('clio.media.work', required=True, ondelete='cascade', index=True)
    context_id = fields.Many2one('clio.reco.context', required=True, ondelete='restrict', index=True)
    user_id = fields.Many2one(
        'res.users', required=True, default=lambda self: self.env.user, index=True
    )
    score = fields.Integer(required=True)
    comment = fields.Text()
    date = fields.Datetime(default=fields.Datetime.now)
    visibility = fields.Selection(
        [('private', 'Privat'), ('public', 'Publik')],
        default='private',
        required=True,
    )
    consent = fields.Selection(
        [('unset', 'Ej angivet'), ('given', 'Givet'), ('withdrawn', 'Återkallat')],
        default='unset',
        required=True,
    )
    origin = fields.Selection(
        [('manual', 'Manuellt'), ('import', 'Import'), ('ai', 'AI')],
        default='manual',
        required=True,
    )
    source = fields.Char()

    _unique_work_context_user = models.Constraint(
        'UNIQUE(work_id, context_id, user_id)',
        'Betyg per verk, sammanhang och användare måste vara unikt.',
    )

    @api.constrains('score', 'context_id', 'work_id', 'user_id')
    def _check_rating(self):
        for rec in self:
            ctx = rec.context_id
            if not ctx:
                continue
            if not (ctx.scale_min <= rec.score <= ctx.scale_max):
                raise ValidationError(
                    f'Betyget {rec.score} är utanför sammanhangets skala '
                    f'{ctx.scale_min}–{ctx.scale_max}.'
                )
            if ctx.state != 'approved':
                raise ValidationError('Betyg kan bara ges i godkända sammanhang.')
            if ctx.work_type_ids and rec.work_id.work_type_id not in ctx.work_type_ids:
                raise ValidationError(
                    f'Verkstypen "{rec.work_id.work_type_id.name}" '
                    f'är inte tillåten i sammanhanget "{ctx.name}".'
                )
            if ctx.rater_group_ids and not self.env.su:
                if not self.env.user.has_group('clio_reco.group_clio_reco_manager'):
                    if not (ctx.rater_group_ids & self.env.user.groups_id):
                        raise ValidationError(
                            f'Du saknar behörighet att betygsätta i sammanhanget "{ctx.name}".'
                        )

    def write(self, vals):
        if 'score' in vals:
            vals = dict(vals, date=fields.Datetime.now())
        return super().write(vals)
