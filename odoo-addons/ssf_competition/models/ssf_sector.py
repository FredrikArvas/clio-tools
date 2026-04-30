from odoo import models, fields, api


class SsfSector(models.Model):
    _name = "ssf.sector"
    _description = "SSF Sector"
    _order = "sort_order, name"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    name = fields.Char(string="Name", required=True, readonly=True)
    sector_code = fields.Char(string="Code", readonly=True)
    hidden = fields.Boolean(string="Hidden", readonly=True)
    sort_order = fields.Integer(string="Sort Order", readonly=True)
    fis_sector_code = fields.Char(string="FIS Code", readonly=True)

    event_count = fields.Integer(string="Evenemang", compute="_compute_counts")
    competition_count = fields.Integer(string="Tävlingar", compute="_compute_counts")

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
            "view_mode": "list,kanban,calendar,form",
            "domain": [("sector_id", "=", self.id)],
            "context": {"search_default_current_season": 1, "create": False},
        }

    def action_view_competitions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Tävlingar — {self.name}",
            "res_model": "ssf.competition",
            "view_mode": "list,form",
            "domain": [("sector_id", "=", self.id)],
            "context": {"search_default_current_season": 1, "create": False},
        }
