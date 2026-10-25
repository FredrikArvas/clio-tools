from odoo import fields, models


class RecoRatingStat(models.Model):
    _name = 'clio.reco.rating.stat'
    _description = 'Betygsstatistik (SQL-vy)'
    _auto = False
    _rec_name = 'work_id'

    work_id = fields.Many2one('clio.media.work', readonly=True, string='Verk')
    context_id = fields.Many2one('clio.reco.context', readonly=True, string='Sammanhang')
    rating_count = fields.Integer(readonly=True, string='Antal betyg')
    avg_score = fields.Float(readonly=True, digits=(6, 2), string='Snittbetyg')

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW clio_reco_rating_stat AS
            SELECT
                min(r.id) AS id,
                r.work_id,
                r.context_id,
                count(r.id) AS rating_count,
                round(avg(r.score)::numeric, 2) AS avg_score
            FROM clio_reco_rating r
            JOIN clio_reco_context c ON c.id = r.context_id
            WHERE
                r.consent = 'given'
                OR (r.consent = 'unset' AND c.is_sensitive = FALSE)
            GROUP BY r.work_id, r.context_id
        """)
