"""
res_partner.py
Utökar res.partner med dödsannonsbevakningsfält.
"""

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ── Bevakningsrelationer ──────────────────────────────────────────────────

    watch_ids = fields.One2many(
        comodel_name = "clio.obit.watch",
        inverse_name = "partner_id",
        string       = "Bevakningar",
    )
    clio_obit_watch = fields.Boolean(
        string   = "Bevakad",
        compute  = "_compute_clio_obit_watch",
        store    = True,
        help     = "True om minst en användare bevakar den här personen.",
    )

    @api.depends("watch_ids")
    def _compute_clio_obit_watch(self):
        for rec in self:
            rec.clio_obit_watch = bool(rec.watch_ids)

    # ── Övriga Clio-fält ──────────────────────────────────────────────────────

    clio_obit_birth_name = fields.Char(
        string = "Födelsenamn",
        help   = "Namn vid födseln (flicknamn/ogift namn). "
                 "Används som matchningsnyckel vid GEDCOM-import.",
    )
    clio_family_role = fields.Char(
        string = "Familjeroll",
        help   = "T.ex. farfar, faster, granne",
    )
    clio_link_ids = fields.One2many(
        comodel_name = "clio.partner.link",
        inverse_name = "from_partner_id",
        string       = "Familjerelationer",
    )
