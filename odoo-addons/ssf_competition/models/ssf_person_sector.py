from odoo import models, fields


class SsfPersonSector(models.Model):
    _name = 'ssf.person.sector'
    _description = 'Person-gren-koppling'

    person_id = fields.Many2one('res.partner', required=True, ondelete='cascade', index=True)
    sector_id = fields.Many2one('ssf.sector', required=True, ondelete='cascade', index=True)

    _unique_person_sector = models.Constraint(
        "UNIQUE(person_id, sector_id)",
        "Dublettrad",
    )
