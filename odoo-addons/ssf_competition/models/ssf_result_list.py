from odoo import models, fields, api


class SsfResultList(models.Model):
    _name = "ssf.result.list"
    _description = "SSF Result List"
    _order = "ccd_id, id"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    ccd_id = fields.Many2one("ssf.comp.ccd", string="Class/Discipline", readonly=True, index=True, ondelete="cascade")
    competition_id = fields.Many2one(related="ccd_id.competition_id", string="Competition", store=True, readonly=True)
    final = fields.Integer(string="Final", readonly=True)
    class_name = fields.Char(string="Class", readonly=True)
    discipline_name = fields.Char(string="Discipline", readonly=True)
    participants_registered = fields.Integer(string="Registered", readonly=True)
    participants_started = fields.Integer(string="Started", readonly=True)
    participants_completed = fields.Integer(string="Completed", readonly=True)
    result_ids = fields.One2many("ssf.result", "result_list_id", string="Results")
    name = fields.Char(string='Namn', compute='_compute_name')

    @api.depends('class_name', 'discipline_name', 'ssfta_id')
    def _compute_name(self):
        for rec in self:
            parts = [p for p in [rec.class_name, rec.discipline_name] if p]
            rec.name = ' / '.join(parts) if parts else str(rec.ssfta_id or '')
