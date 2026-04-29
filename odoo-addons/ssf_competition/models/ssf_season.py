from odoo import models, fields


class SsfSeason(models.Model):
    _name = "ssf.season"
    _description = "SSF Season"
    _order = "ssfta_id desc"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    name = fields.Char(string="Name", required=True, readonly=True)