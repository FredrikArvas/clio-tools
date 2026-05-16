"""
clio_obit_match.py
En matchningspost som Clio skapar varje gång en dödsannons
når tröskeln och matchar en bevakad person.
"""

from odoo import models, fields


class ClioObitMatch(models.Model):
    _name        = "clio.obit.match"
    _description = "Clio Obit — Matchning"
    _order       = "notified_at desc"
    _rec_name    = "partner_id"

    announcement_id = fields.Many2one(
        comodel_name = "clio.obit.announcement",
        string       = "Annons",
        required     = True,
        ondelete     = "cascade",
        index        = True,
    )
    partner_id = fields.Many2one(
        comodel_name = "res.partner",
        string       = "Bevakad person",
        required     = True,
        index        = True,
    )
    score = fields.Integer(
        string = "Konfidenspoäng",
        help   = "Matchningspoäng. Tröskelvärde: ≥ 60.",
    )
    priority = fields.Selection(
        selection = [
            ("viktig",       "Viktig — direkt notis"),
            ("normal",       "Normal — daglig digest"),
            ("bra_att_veta", "Bra att veta"),
        ],
        string = "Prioritet",
    )
    notified_at = fields.Datetime(
        string = "Notifierad",
        help   = "Tidsstämpel för när notisen skickades. Tom = ej skickad.",
    )
    suppressed = fields.Boolean(
        string = "Supprimerad",
        help   = "True om träffen var äldre än grace-perioden — ingen notis skickad.",
    )

    # Denormaliserade fält för snabb listvy utan joins
    ann_name = fields.Char(
        related = "announcement_id.name",
        string  = "Namn i annonsen",
        store   = True,
    )
    ann_source = fields.Char(
        related = "announcement_id.source_name",
        string  = "Källa",
        store   = True,
    )
    ann_date = fields.Date(
        related = "announcement_id.published_date",
        string  = "Publicerad",
        store   = True,
    )
    ann_url = fields.Char(
        related = "announcement_id.url",
        string  = "URL",
        store   = True,
    )
