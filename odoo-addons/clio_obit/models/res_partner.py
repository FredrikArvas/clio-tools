"""
res_partner.py
Utökar res.partner med dödsannonsbevakningsfält.
"""

import re

from odoo import api, fields, models

_YEAR_RE = re.compile(r'\b(1[5-9]\d{2}|20[012]\d)\b')


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
    clio_obit_birth_approx = fields.Char(
        string = "Födelseuppgift",
        help   = "Fritt format: '1952', 'ca 1952', 'mars 1952', '1952-03-15', '1940-talet'.",
    )
    clio_obit_birth_year = fields.Integer(
        string  = "Födelseår (extraherat)",
        compute = "_compute_clio_obit_birth_year",
        store   = True,
        help    = "Automatiskt extraherat årtalet ur Födelseuppgift. 0 = okänt.",
    )

    @api.depends("clio_obit_birth_approx")
    def _compute_clio_obit_birth_year(self):
        for rec in self:
            m = _YEAR_RE.search(rec.clio_obit_birth_approx or "")
            rec.clio_obit_birth_year = int(m.group(1)) if m else 0
    clio_obit_death_year = fields.Integer(
        string  = "Dödsår",
        default = 0,
        help    = "Dödsår från GEDCOM eller manuellt. 0 = okänt.",
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
