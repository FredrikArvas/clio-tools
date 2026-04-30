from odoo import models, fields, api


SECTOR_VISUAL = {
    'AL':  {'emoji': '🎿', 'c1': '#8B4B4B', 'c2': '#C47A7A'},
    'CC':  {'emoji': '⛷️',  'c1': '#3E6B55', 'c2': '#5E9E7E'},
    'SB':  {'emoji': '🏂', 'c1': '#5C4E8A', 'c2': '#8A72B8'},
    'FS':  {'emoji': '🤸', 'c1': '#3A5E8A', 'c2': '#5A88BA'},
    'FR':  {'emoji': '🎿', 'c1': '#3A7A80', 'c2': '#5AAAB0'},
    'JP':  {'emoji': '🦅', 'c1': '#3A5068', 'c2': '#567290'},
    'NK':  {'emoji': '🎯', 'c1': '#3A6860', 'c2': '#559080'},
    'RS':  {'emoji': '🛼', 'c1': '#8A6238', 'c2': '#BA8E58'},
    'SX':  {'emoji': '🏁', 'c1': '#8A5C3A', 'c2': '#BA8458'},
    'SO':  {'emoji': '🧭', 'c1': '#3E6858', 'c2': '#5A9278'},
    'SS':  {'emoji': '💨', 'c1': '#4A5E6E', 'c2': '#6A8898'},
    'TM':  {'emoji': '🏔️', 'c1': '#5E4A7A', 'c2': '#8868A8'},
    'GS':  {'emoji': '🌿', 'c1': '#4A7245', 'c2': '#6A9E65'},
    'MAS': {'emoji': '🏆', 'c1': '#725C38', 'c2': '#A08258'},
}
DEFAULT_VISUAL = {'emoji': '🏅', 'c1': '#1A252F', 'c2': '#2C3E50'}

CURRENT_SEASON_SSFTA_ID = 18  # 2025/26 — uppdatera vid säsongsskifte


class SsfSector(models.Model):
    _name = "ssf.sector"
    _description = "SSF Sector"
    _order = "sort_order, name"

    ssfta_id    = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    name        = fields.Char(string="Name", required=True, readonly=True)
    sector_code = fields.Char(string="Code", readonly=True)
    hidden      = fields.Boolean(string="Hidden", readonly=True)
    sort_order  = fields.Integer(string="Sort Order", readonly=True)
    fis_sector_code = fields.Char(string="FIS Code", readonly=True)

    event_count = fields.Integer(
        string="Evenemang", compute="_compute_counts", store=True
    )
    competition_count = fields.Integer(
        string="Tävlingar", compute="_compute_counts", store=True
    )

    # Innevarande säsong (CURRENT_SEASON_SSFTA_ID)
    cs_event_count = fields.Integer(
        string="Evenemang (säsong)", compute="_compute_cs_counts", store=True
    )
    cs_competition_count = fields.Integer(
        string="Tävlingar (säsong)", compute="_compute_cs_counts", store=True
    )

    # Visuella fält för kanban
    sport_emoji  = fields.Char(string="Emoji",  compute="_compute_visual", store=True)
    sport_color  = fields.Char(string="Färg 1", compute="_compute_visual", store=True)
    sport_color2 = fields.Char(string="Färg 2", compute="_compute_visual", store=True)

    @api.depends()
    def _compute_cs_counts(self):
        if not self.ids:
            return
        sql = (
            "SELECT e.sector_id,"
            " COUNT(DISTINCT e.id) AS ev_cnt,"
            " COUNT(DISTINCT c.id) AS co_cnt"
            " FROM ssf_event e"
            " LEFT JOIN ssf_competition c ON c.event_id = e.id"
            " JOIN ssf_season s ON e.season_id = s.id"
            " WHERE e.sector_id IN %s AND s.ssfta_id = %s"
            " GROUP BY e.sector_id"
        )
        self.env.cr.execute(sql, [tuple(self.ids), CURRENT_SEASON_SSFTA_ID])
        data = {row[0]: (row[1], row[2]) for row in self.env.cr.fetchall()}
        for rec in self:
            ev, co = data.get(rec.id, (0, 0))
            rec.cs_event_count       = int(ev or 0)
            rec.cs_competition_count = int(co or 0)

    @api.depends("sector_code")
    def _compute_visual(self):
        for rec in self:
            v = SECTOR_VISUAL.get(rec.sector_code or '', DEFAULT_VISUAL)
            rec.sport_emoji  = v['emoji']
            rec.sport_color  = v['c1']
            rec.sport_color2 = v['c2']

    gold_count   = fields.Integer(string="Guld",   compute="_compute_medals", store=True)
    silver_count = fields.Integer(string="Silver", compute="_compute_medals", store=True)
    bronze_count = fields.Integer(string="Brons",  compute="_compute_medals", store=True)

    @api.depends()
    def _compute_counts(self):
        for rec in self:
            rec.event_count = self.env["ssf.event"].search_count(
                [("sector_id", "=", rec.id)]
            )
            rec.competition_count = self.env["ssf.competition"].search_count(
                [("sector_id", "=", rec.id)]
            )

    @api.depends()
    def _compute_medals(self):
        if not self.ids:
            return
        self.env.cr.execute("""
            SELECT e.sector_id,
                SUM(CASE WHEN r.rank = 1 THEN 1 ELSE 0 END),
                SUM(CASE WHEN r.rank = 2 THEN 1 ELSE 0 END),
                SUM(CASE WHEN r.rank = 3 THEN 1 ELSE 0 END)
            FROM ssf_result r
            JOIN ssf_result_list rl ON r.result_list_id = rl.id
            JOIN ssf_comp_ccd ccd ON rl.ccd_id = ccd.id
            JOIN ssf_competition comp ON ccd.competition_id = comp.id
            JOIN ssf_event e ON comp.event_id = e.id
            WHERE e.sector_id IN %s
            GROUP BY e.sector_id
        """, [tuple(self.ids)])
        medal_data = {row[0]: (row[1], row[2], row[3]) for row in self.env.cr.fetchall()}
        for rec in self:
            g, s, b = medal_data.get(rec.id, (0, 0, 0))
            rec.gold_count   = int(g or 0)
            rec.silver_count = int(s or 0)
            rec.bronze_count = int(b or 0)

    def action_view_events(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Evenemang — {self.name}",
            "res_model": "ssf.event",
            "view_mode": "list,kanban,calendar,graph,pivot,form",
            "domain": [("sector_id", "=", self.id)],
            "context": {"search_default_current_season": 1, "create": False},
        }

    def action_view_competitions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Tävlingar — {self.name}",
            "res_model": "ssf.competition",
            "view_mode": "list,graph,pivot,form",
            "domain": [("sector_id", "=", self.id)],
            "context": {"search_default_current_season": 1, "create": False},
        }
