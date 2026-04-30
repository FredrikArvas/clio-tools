from odoo import models, fields


class SsfFisCompetitor(models.Model):
    _name = "ssf.fis.competitor"
    _description = "SSF FIS Competitor"
    _rec_name = "fis_code"
    _order = "discipline_id, fis_rank, fis_points"

    person_id = fields.Many2one("res.partner", string="Person", index=True, ondelete="cascade")
    fis_code = fields.Char(string="FIS-kod", index=True)
    nation = fields.Char(string="Nation")
    discipline_id = fields.Many2one("ssf.discipline", string="Disciplin", ondelete="set null")
    fis_points = fields.Float(string="FIS-poäng")
    fis_rank = fields.Integer(string="FIS-ranking")
    list_date = fields.Date(string="Listdatum")
    source = fields.Selection(
        [("ssfta_derived", "Härledd från SSFTA"), ("fis_api", "FIS API")],
        string="Källa",
        default="ssfta_derived",
        readonly=True,
    )

    _sql_constraints = [
        (
            "fis_competitor_unique",
            "UNIQUE(fis_code, discipline_id)",
            "FIS-kod + disciplin måste vara unik.",
        )
    ]
