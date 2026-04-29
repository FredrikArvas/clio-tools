from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    ssfta_sdf_id = fields.Many2one(
        "res.partner",
        string="Tillhör SDF",
        help=(
            "Denormaliserad SDF-koppling. Sätts av sync_orgs.py på föreningar "
            "och av sync_persons.py på person-partners. SDF-partners pekar på sig själva."
        ),
        ondelete="set null",
        domain=[("ref", "like", "ssfta-")],
    )

    ssfta_club_id = fields.Many2one(
        "res.partner",
        string="Tillhör förening",
        help="Primär förening för person-partner. Sätts av sync_persons.py.",
        ondelete="set null",
        domain=[("ref", "like", "ssfta-")],
    )
