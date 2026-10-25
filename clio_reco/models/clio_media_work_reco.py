from odoo import fields, models


class ClioMediaWorkReco(models.Model):
    _inherit = 'clio.media.work'

    rating_ids = fields.One2many('clio.reco.rating', 'work_id', string='Betyg')
    rating_count = fields.Integer(compute='_compute_rating_count', string='Antal betyg')

    def _compute_rating_count(self):
        rating_data = self.env['clio.reco.rating'].read_group(
            [('work_id', 'in', self.ids)],
            ['work_id'],
            ['work_id'],
        )
        counts = {d['work_id'][0]: d['work_id_count'] for d in rating_data}
        for rec in self:
            rec.rating_count = counts.get(rec.id, 0)

    def action_view_ratings(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Betyg',
            'res_model': 'clio.reco.rating',
            'view_mode': 'list,form',
            'domain': [('work_id', '=', self.id)],
            'context': {'default_work_id': self.id},
        }
