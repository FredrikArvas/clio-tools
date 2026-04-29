from odoo import models, fields

COMP_STATUS = [
    ('1', 'Ny'),
    ('2', 'Ansökt'),
    ('3', 'Godkänd'),
    ('4', 'Anmälan öppen'),
    ('5', '(ingen)'),
    ('6', 'Genomförd'),
    ('7', 'Flyttad'),
    ('8', 'Inställd'),
]


class SsfCompetition(models.Model):
    _name = "ssf.competition"
    _description = "SSF Competition"
    _order = "date desc"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    name = fields.Char(string="Name", required=True, readonly=True)
    event_id = fields.Many2one("ssf.event", string="Event", readonly=True, index=True, ondelete="cascade")
    sector_id = fields.Many2one(related="event_id.sector_id", string="Sector", store=True, readonly=True)
    season_id = fields.Many2one(related="event_id.season_id", string="Season", store=True, readonly=True)
    date = fields.Date(string="Date", readonly=True)
    competition_status = fields.Selection(COMP_STATUS, string="Status", readonly=True)
    last_entry_date = fields.Datetime(string="Last Entry Date", readonly=True)
    entry_open = fields.Boolean(string="Entry Open", readonly=True)
    live_results_link = fields.Char(string="Live Results", readonly=True)
    ccd_ids = fields.One2many("ssf.comp.ccd", "competition_id", string="Classes/Disciplines")
    entry_count = fields.Integer(string="Entries", compute="_compute_counts", store=False)
    result_count = fields.Integer(string="Results", compute="_compute_counts", store=False)

    def _compute_counts(self):
        Entry = self.env["ssf.entry"]
        Result = self.env["ssf.result"]
        for rec in self:
            ccd_ids = rec.ccd_ids.ids
            if ccd_ids:
                rec.entry_count = Entry.search_count([("ccd_id", "in", ccd_ids)])
                rl_ids = self.env["ssf.result.list"].search([("ccd_id", "in", ccd_ids)]).ids
                rec.result_count = Result.search_count([("result_list_id", "in", rl_ids)]) if rl_ids else 0
            else:
                rec.entry_count = 0
                rec.result_count = 0

    def action_sync_results(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Sync Results",
                "message": (
                    f"Run on server: "
                    f"cd ~/clio-tools/clio-odoo-ssfta && "
                    f"python3 sync_competition_results.py --competition-id {self.ssfta_id}"
                ),
                "type": "info",
                "sticky": True,
            },
        }
