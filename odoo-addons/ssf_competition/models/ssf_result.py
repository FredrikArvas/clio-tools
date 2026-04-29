from odoo import models, fields


class SsfResult(models.Model):
    _name = "ssf.result"
    _description = "SSF Result"
    _order = "result_list_id, rank, display_order"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    result_list_id = fields.Many2one("ssf.result.list", string="Result List", readonly=True, index=True, ondelete="cascade")
    person_id = fields.Many2one("res.partner", string="Person", readonly=True, ondelete="set null")
    rank = fields.Integer(string="Rank", readonly=True)
    bib = fields.Integer(string="Bib", readonly=True)
    fis_code = fields.Integer(string="FIS Code", readonly=True)
    firstname = fields.Char(string="First Name", readonly=True)
    lastname = fields.Char(string="Last Name", readonly=True)
    birth_year = fields.Integer(string="Birth Year", readonly=True)
    nation = fields.Char(string="Nation", readonly=True)
    gender = fields.Char(string="Gender", readonly=True)
    club = fields.Char(string="Club", readonly=True)
    club_id = fields.Many2one("res.partner", string="Club (link)", readonly=True, ondelete="set null")
    status = fields.Char(string="Status", readonly=True)
    time = fields.Char(string="Time", readonly=True)
    difference = fields.Char(string="Diff", readonly=True)
    points = fields.Char(string="Points", readonly=True)
    fis_points = fields.Char(string="FIS Points", readonly=True)
    display_order = fields.Integer(string="Display Order", readonly=True)