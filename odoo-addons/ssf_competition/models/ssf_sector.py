from odoo import models, fields, api


SECTOR_VISUAL = {
    'AL':  {'emoji': '🎿', 'c1': '#6B3A3A', 'c2': '#9E5A5A'},
    'CC':  {'emoji': '⛷️',  'c1': '#345244', 'c2': '#4D7A62'},
    'SB':  {'emoji': '🏂', 'c1': '#4A3A6B', 'c2': '#6E5A96'},
    'FS':  {'emoji': '🤸', 'c1': '#2E4A6B', 'c2': '#4A6D96'},
    'FR':  {'emoji': '🎿', 'c1': '#2E5C60', 'c2': '#447E83'},
    'JP':  {'emoji': '🦅', 'c1': '#2E3D4F', 'c2': '#455870'},
    'NK':  {'emoji': '🎯', 'c1': '#2E5048', 'c2': '#447062'},
    'RS':  {'emoji': '🛼', 'c1': '#6B4E2E', 'c2': '#96703F'},
    'SX':  {'emoji': '🏁', 'c1': '#6B4830', 'c2': '#966245'},
    'SO':  {'emoji': '🧭', 'c1': '#335245', 'c2': '#4A7260'},
    'SS':  {'emoji': '💨', 'c1': '#3A4A55', 'c2': '#566878'},
    'TM':  {'emoji': '🏔️', 'c1': '#4A3A60', 'c2': '#6B5585'},
    'GS':  {'emoji': '🌿', 'c1': '#3A5A35', 'c2': '#567A4F'},
    'MAS': {'emoji': '🏆', 'c1': '#5A4A2E', 'c2': '#7D6840'},
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
