from odoo import models, fields, api


class SsfCompCcd(models.Model):
    _name = "ssf.comp.ccd"
    _description = "SSF Class x Discipline (CCD)"
    _order = "competition_id, id"

    ssfta_id = fields.Integer(string="SSFTA ID", index=True, readonly=True)
    competition_id = fields.Many2one("ssf.competition", string="Competition", readonly=True, index=True, ondelete="cascade")
    class_id = fields.Many2one("ssf.comp.class", string="Class", readonly=True, ondelete="set null")
    discipline_id = fields.Many2one("ssf.discipline", string="Discipline", readonly=True, ondelete="set null")
    distance = fields.Char(string="Distance", readonly=True)
    fis_codex = fields.Integer(string="FIS Codex", readonly=True)
    non_member_entry = fields.Boolean(string="Non-Member Entry", readonly=True)
    foreign_entry = fields.Boolean(string="Foreign Entry", readonly=True)
    result_list_ids = fields.One2many("ssf.result.list", "ccd_id", string="Result Lists")
    entry_ids = fields.One2many("ssf.entry", "ccd_id", string="Entries")
    name = fields.Char(string="Name", compute="_compute_name")

    @api.depends("class_id", "discipline_id", "ssfta_id")
    def _compute_name(self):
        for rec in self:
            parts = [p for p in [
                rec.class_id.name if rec.class_id else None,
                rec.discipline_id.short_name or rec.discipline_id.name if rec.discipline_id else None,
            ] if p]
            rec.name = " / ".join(parts) if parts else str(rec.ssfta_id or "")