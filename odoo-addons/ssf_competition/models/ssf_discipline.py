from odoo import models, fields


class SsfDiscipline(models.Model):
    _name = "ssf.discipline"
    _description = "SSF Discipline"
    _order = "sector_id, sort_order, name"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    name = fields.Char(string="Name", required=True, readonly=True)
    short_name = fields.Char(string="Short Name", readonly=True)
    sector_id = fields.Many2one("ssf.sector", string="Sector", readonly=True, ondelete="set null")
    hidden = fields.Boolean(string="Hidden", readonly=True)
    sort_order = fields.Integer(string="Sort Order", readonly=True)
    team_entry = fields.Boolean(string="Team Entry", readonly=True)