from odoo import models, fields, api

EVENT_STATUS = [
    ('1', 'Ny'),
    ('2', 'Ansökt'),
    ('3', 'Godkänt'),
    ('4', 'Anmälan öppen'),
    ('5', '(ingen)'),
    ('6', 'Genomfört'),
    ('7', 'Flyttat'),
    ('8', 'Inställt'),
]

GEO_SCOPE = [
    ('1',  'Klubb'),
    ('3',  'Distrikt'),
    ('5',  'Region'),
    ('6',  'Landsdel'),
    ('7',  'Nationell'),
    ('8',  'Internationell (FIS)'),
    ('9',  'Klubb (Lokalt)'),
    ('10', 'Nordisk'),
]


class SsfEvent(models.Model):
    _name = "ssf.event"
    _description = "SSF Event"
    _order = "start_date desc"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    name = fields.Char(string="Name", required=True, readonly=True)
    sector_id = fields.Many2one("ssf.sector", string="Sector", readonly=True, index=True, ondelete="set null")
    season_id = fields.Many2one("ssf.season", string="Season", readonly=True, index=True, ondelete="set null")
    start_date = fields.Date(string="Start Date", readonly=True)
    end_date = fields.Date(string="End Date", readonly=True)
    place = fields.Char(string="Place", readonly=True)
    city = fields.Char(string="City", readonly=True)
    organizer_id = fields.Many2one("res.partner", string="Organizer", readonly=True, ondelete="set null")
    event_type = fields.Char(string="Type", readonly=True)
    event_status = fields.Selection(EVENT_STATUS, string="Status", readonly=True)
    geographical_scope = fields.Selection(GEO_SCOPE, string="Räckvidd", readonly=True, index=True)
    event_type_label   = fields.Char(string="Tävlingstyp", readonly=True)
    note = fields.Text(string="Note", readonly=True)
    email = fields.Char(string="Email", readonly=True)
    website = fields.Char(string="Website", readonly=True)
    competition_ids = fields.One2many("ssf.competition", "event_id", string="Competitions")

    # store=True → sorterbara i listvy
    competition_count = fields.Integer(
        string="Competition Count", compute="_compute_competition_count", store=True
    )
    entry_count = fields.Integer(
        string="Entries", compute="_compute_counts", store=True
    )
    result_count = fields.Integer(
        string="Results", compute="_compute_counts", store=True
    )

    @api.depends("competition_ids")
    def _compute_competition_count(self):
        for rec in self:
            rec.competition_count = len(rec.competition_ids)

    # Kaskad: competition.entry_count/result_count → event räknas om automatiskt
    @api.depends("competition_ids.entry_count", "competition_ids.result_count")
    def _compute_counts(self):
        for rec in self:
            rec.entry_count = sum(c.entry_count for c in rec.competition_ids)
            rec.result_count = sum(c.result_count for c in rec.competition_ids)
