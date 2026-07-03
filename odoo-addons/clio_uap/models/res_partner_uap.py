from odoo import models, fields


class ResPartnerUap(models.Model):
    _inherit = "res.partner"

    uap_org_type = fields.Selection(
        selection=[
            ("ufo_org",    "UFO / UAP Research Org"),
            ("govt",       "Government / Military"),
            ("scientific", "Scientific / Academic"),
            ("civilian",   "Civilian / Nonprofit"),
            ("lobby",      "Policy / Lobby"),
            ("archive",    "Archive / Library"),
        ],
        string="UAP Org Type",
        index=True,
    )
    uap_encounter_id = fields.Char(string="UAP Org ID", index=True,
                                   help="PPXL-stil ID, t.ex. SWE_1973_UFOSE")
    uap_region = fields.Selection(
        selection=[
            ("europe",        "Europe"),
            ("north_america", "North America"),
            ("south_america", "South America"),
            ("asia",          "Asia"),
            ("africa",        "Africa"),
            ("oceania",       "Oceania"),
            ("middle_east",   "Middle East"),
        ],
        string="UAP Region",
    )
    uap_discourse_level = fields.Selection(
        selection=[
            ("1", "1 — Fringe / Unknown"),
            ("2", "2 — Limited Public Awareness"),
            ("3", "3 — Active Public Debate"),
            ("4", "4 — Official Acknowledgement"),
            ("5", "5 — Confirmed / Declassified"),
        ],
        string="Discourse Level",
    )
    uap_official_response = fields.Selection(
        selection=[
            ("A", "A — No Response"),
            ("B", "B — Denial"),
            ("C", "C — Acknowledgement"),
            ("D", "D — Investigation"),
            ("E", "E — Confirmation"),
        ],
        string="Official Response",
    )
    uap_research_notes = fields.Text(string="UAP Research Notes")
    uap_database_ids = fields.One2many(
        comodel_name="uap.database",
        inverse_name="partner_id",
        string="UAP Databases",
    )
    uap_database_count = fields.Integer(
        string="# Databases",
        compute="_compute_uap_database_count",
        store=False,
    )

    def _compute_uap_database_count(self):
        for rec in self:
            rec.uap_database_count = len(rec.uap_database_ids)
