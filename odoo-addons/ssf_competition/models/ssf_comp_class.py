from odoo import models, fields


class SsfCompClass(models.Model):
    _name = "ssf.comp.class"
    _description = "SSF Competition Class"
    _order = "sector_id, sort_order, name"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    name = fields.Char(string="Name", required=True, readonly=True)
    local_name = fields.Char(string="Local Name", readonly=True)
    sector_id = fields.Many2one("ssf.sector", string="Sector", readonly=True, ondelete="set null")
    from_age = fields.Integer(string="Min Age", readonly=True)
    to_age = fields.Integer(string="Max Age", readonly=True)
    gender = fields.Char(string="Gender", readonly=True)
    hidden = fields.Boolean(string="Hidden", readonly=True)
    sort_order = fields.Integer(string="Sort Order", readonly=True)