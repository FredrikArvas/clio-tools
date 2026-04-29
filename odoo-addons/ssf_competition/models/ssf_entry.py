from odoo import models, fields


class SsfEntry(models.Model):
    _name = "ssf.entry"
    _description = "SSF Entry"
    _order = "ccd_id, entry_date"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    ccd_id = fields.Many2one("ssf.comp.ccd", string="Class/Discipline", readonly=True, index=True, ondelete="cascade")
    competition_id = fields.Many2one(related="ccd_id.competition_id", string="Competition", store=True, readonly=True)
    person_id = fields.Many2one("res.partner", string="Person", readonly=True, ondelete="set null")
    organization_id = fields.Many2one("res.partner", string="Organization", readonly=True, ondelete="set null")
    entry_date = fields.Datetime(string="Entry Date", readonly=True)
    entry_fee = fields.Integer(string="Entry Fee", readonly=True)
    paid_fee = fields.Integer(string="Paid Fee", readonly=True)
    payment_status = fields.Integer(string="Payment Status", readonly=True)
    unregistered = fields.Boolean(string="Unregistered", readonly=True)
    unreg_date = fields.Datetime(string="Unregistration Date", readonly=True)
    note = fields.Text(string="Note", readonly=True)