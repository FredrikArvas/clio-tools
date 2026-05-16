"""
clio_obit_watch.py
Bevakningsrelation: en res.users bevakar en res.partner för dödsannonser.

En person kan bevakas av flera användare med individuell prioritet och
notifieringsadress. Ersätter de gamla fälten clio_obit_priority och
clio_obit_notify_email på res.partner.
"""

from __future__ import annotations

import unicodedata

from odoo import api, fields, models

import logging
_logger = logging.getLogger(__name__)


def _norm(s: str) -> str:
    """Lowercase + strip diacritics för jämförelse."""
    s = (s or "").strip().lower()
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


class ClioObitWatch(models.Model):
    _name        = "clio.obit.watch"
    _description = "Clio Obit — Bevakningsrelation"
    _order       = "partner_name, priority"
    _rec_name    = "partner_id"

    partner_id = fields.Many2one(
        comodel_name = "res.partner",
        string       = "Person",
        required     = True,
        ondelete     = "cascade",
        domain       = [("is_company", "=", False)],
        index        = True,
    )
    user_id = fields.Many2one(
        comodel_name = "res.users",
        string       = "Bevakare",
        required     = True,
        ondelete     = "cascade",
        default      = lambda self: self.env.user,
        index        = True,
    )
    priority = fields.Selection(
        selection = [
            ("viktig",       "Viktig — direkt notis"),
            ("normal",       "Normal — daglig digest"),
            ("bra_att_veta", "Bra att veta"),
        ],
        string   = "Prioritet",
        default  = "normal",
        required = True,
    )
    family_role = fields.Char(
        string = "Familjeroll",
        help   = "Din relation till den här personen, t.ex. farfar, faster, granne. "
                 "Gäller bara för dig som bevakare.",
    )
    notify_email = fields.Char(
        string = "Notifiera e-post",
        help   = "Lämnas tomt = användarens e-postadress används.",
    )
    effective_email = fields.Char(
        string  = "Effektiv e-post",
        compute = "_compute_effective_email",
    )

    # Denormaliserade fält för effektiv listvy
    partner_name = fields.Char(
        related = "partner_id.name",
        string  = "Namn",
        store   = True,
    )
    partner_birth_name = fields.Char(
        related = "partner_id.clio_obit_birth_name",
        string  = "Födelsenamn",
        store   = True,
    )

    _sql_constraints = [
        (
            "partner_user_uniq",
            "UNIQUE(partner_id, user_id)",
            "Du bevakar redan den här personen.",
        ),
    ]

    @api.depends("notify_email", "user_id", "user_id.email")
    def _compute_effective_email(self):
        for rec in self:
            rec.effective_email = rec.notify_email or rec.user_id.email or ""

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._retroactive_match()
        return records

    def _retroactive_match(self):
        """
        Söker befintliga annonser efter ett nyskapat watch.
        Kör vid create() — täcker fallet att annonsen redan indexerats
        men ingen bevakning fanns vid scantillfället.
        """
        match_name = self.partner_birth_name or self.partner_name or ""
        parts = match_name.strip().split()
        if not parts:
            return

        w_efternamn_raw = parts[-1]
        w_efternamn = _norm(w_efternamn_raw)
        w_fornamn = _norm(" ".join(parts[:-1]))
        birth_year = self.partner_id.clio_obit_birth_year or 0
        partner_city = _norm(self.partner_id.city or "")
        partner_id = self.partner_id.id

        # ilike-filtrering på DB-nivå, normalisering i Python
        candidates = self.env["clio.obit.announcement"].search([
            ("efternamn", "ilike", w_efternamn_raw),
        ])

        hits = 0
        for ann in candidates:
            a_efternamn = _norm(ann.efternamn or "")
            a_fornamn = _norm(ann.fornamn or "")

            if a_efternamn != w_efternamn:
                continue

            score = 40  # exakt efternamn

            if w_fornamn and a_fornamn:
                if a_fornamn == w_fornamn:
                    score += 30
                elif w_fornamn[:3] and a_fornamn.startswith(w_fornamn[:3]):
                    score += 10

            if birth_year and ann.fodelsear:
                if abs(birth_year - ann.fodelsear) <= 5:
                    score += 20

            if partner_city and ann.hemort:
                if partner_city == _norm(ann.hemort):
                    score += 10

            if score < 60:
                continue

            existing = self.env["clio.obit.match"].search([
                ("announcement_id", "=", ann.id),
                ("partner_id", "=", partner_id),
            ], limit=1)
            if existing:
                continue

            self.env["clio.obit.match"].create({
                "announcement_id": ann.id,
                "partner_id":      partner_id,
                "score":           score,
                "priority":        self.priority,
                "notified_at":     None,
            })
            ann.write({
                "matched": True,
                "mentioned_partner_ids": [(4, partner_id)],
            })
            hits += 1
            _logger.info(
                "Retroaktiv träff: %s (score=%d) → partner %s",
                ann.name, score, self.partner_id.name,
            )

        if hits:
            _logger.info(
                "Retroaktiv sökning för %s: %d träff(ar) i befintliga annonser.",
                self.partner_id.name, hits,
            )
