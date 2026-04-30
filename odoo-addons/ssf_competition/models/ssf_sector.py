from odoo import models, fields, api


SECTOR_VISUAL = {
    'AL':  {'emoji': '🎿', 'c1': '#7B0D00', 'c2': '#C0392B'},
    'CC':  {'emoji': '⛷️',  'c1': '#0A3D1F', 'c2': '#1E8449'},
    'SB':  {'emoji': '🏂', 'c1': '#3B0764', 'c2': '#7D3C98'},
    'FS':  {'emoji': '🤸', 'c1': '#0B2545', 'c2': '#1A5276'},
    'FR':  {'emoji': '🎿', 'c1': '#004D51', 'c2': '#0097A7'},
    'JP':  {'emoji': '🦅', 'c1': '#0D1B2A', 'c2': '#2C3E50'},
    'NK':  {'emoji': '🎯', 'c1': '#063B34', 'c2': '#117A65'},
    'RS':  {'emoji': '🛼', 'c1': '#5C3000', 'c2': '#B7770D'},
    'SX':  {'emoji': '🏁', 'c1': '#4A2000', 'c2': '#AF601A'},
    'SO':  {'emoji': '🧭', 'c1': '#0B3D1E', 'c2': '#196F3D'},
    'SS':  {'emoji': '💨', 'c1': '#17202A', 'c2': '#566573'},
    'TM':  {'emoji': '🏔️', 'c1': '#2D0B46', 'c2': '#6C3483'},
    'GS':  {'emoji': '🌿', 'c1': '#0E3D1E', 'c2': '#239B56'},
    'MAS': {'emoji': '🏆', 'c1': '#4D3A00', 'c2': '#9A7D0A'},
}
DEFAULT_VISUAL = {'emoji': '🏅', 'c1': '#1A252F', 'c2': '#2C3E50'}


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

    # Visuella fält för kanban
    sport_emoji  = fields.Char(string="Emoji",  compute="_compute_visual", store=True)
    sport_color  = fields.Char(string="Färg 1", compute="_compute_visual", store=True)
    sport_color2 = fields.Char(string="Färg 2", compute="_compute_visual", store=True)

    @api.depends("sector_code")
    def _compute_visual(self):
        for rec in self:
            v = SECTOR_VISUAL.get(rec.sector_code or '', DEFAULT_VISUAL)
            rec.sport_emoji  = v['emoji']
            rec.sport_color  = v['c1']
            rec.sport_color2 = v['c2']

    @api.depends()
    def _compute_counts(self):
        for rec in self:
            rec.event_count = self.env["ssf.event"].search_count(
                [("sector_id", "=", rec.id)]
            )
            rec.competition_count = self.env["ssf.competition"].search_count(
                [("sector_id", "=", rec.id)]
            )

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
