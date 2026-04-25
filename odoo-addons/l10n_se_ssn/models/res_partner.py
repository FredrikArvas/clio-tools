"""
res_partner.py — ssn_se
Lägger till personnummer på res.partner med Luhn-validering.

Accepterade format vid inmatning:
    YYYYMMDD-NNNN  (13 tecken, föredragen standard)
    YYMMDD-NNNN    (11 tecken)
    YYYYMMDDNNNN   (12 siffror, utan bindestreck)
    YYMMDDNNNN     (10 siffror, utan bindestreck)

Lagras alltid som YYYYMMDD-NNNN om födelseåret är tvetydigt normaliseras det
inte — användaren ansvarar för att mata in rätt sekelsiffror.
"""

from __future__ import annotations

import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


def _normalize_to_10(pnr: str) -> str | None:
    """
    Normaliserar till 10 siffror (YYMMDDNNNN) för Luhn-kontroll.
    Returnerar None om formatet inte känns igen.
    """
    s = pnr.strip().replace(" ", "")
    digits = re.sub(r"[-+]", "", s)
    if len(digits) == 12:   # YYYYMMDDNNNN
        digits = digits[2:]
    if re.fullmatch(r"\d{10}", digits):
        return digits
    return None


def _luhn_ok(digits10: str) -> bool:
    """
    Luhn-kontroll för svenska personnummer (10-siffrig form).
    Källa: https://www.samlogic.com/blogg/2012/11/validering-av-personnummer/

    Algoritm:
      1. Multiplicera position 1–9 alternerande med 2 och 1.
      2. Summera alla siffror i produkterna (11 → 1+1=2).
      3. Kontrollsiffra (pos 10) = (10 - summa % 10) % 10.
    """
    mult = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = 0
    for i, m in enumerate(mult):
        p = int(digits10[i]) * m
        total += p // 10 + p % 10
    return (10 - total % 10) % 10 == int(digits10[9])


def _format_pnr(pnr: str) -> str:
    """Normaliserar till YYYYMMDD-NNNN eller YYMMDD-NNNN med bindestreck."""
    s = pnr.strip().replace(" ", "")
    # Ta redan inskrivet bindestreck som det är, lägg till om det saknas
    if "-" in s or "+" in s:
        return s
    digits = s
    if len(digits) == 12:
        return f"{digits[:8]}-{digits[8:]}"
    if len(digits) == 10:
        return f"{digits[:6]}-{digits[6:]}"
    return s


class ResPartner(models.Model):
    _inherit = "res.partner"

    personnummer = fields.Char(
        string="Personnummer",
        size=13,
        help="Format: YYYYMMDD-NNNN. Valideras med Luhn-algoritmen.",
        index=True,
    )

    @api.constrains("personnummer")
    def _check_personnummer(self):
        for rec in self:
            pnr = rec.personnummer
            if not pnr:
                continue
            digits10 = _normalize_to_10(pnr)
            if digits10 is None:
                raise ValidationError(
                    f"Personnummer '{pnr}' har ogiltigt format.\n"
                    "Använd YYYYMMDD-NNNN eller YYMMDD-NNNN."
                )
            if not _luhn_ok(digits10):
                raise ValidationError(
                    f"Personnummer '{pnr}' är ogiltigt (Luhn-kontroll misslyckades)."
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("personnummer"):
                vals["personnummer"] = _format_pnr(vals["personnummer"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("personnummer"):
            vals["personnummer"] = _format_pnr(vals["personnummer"])
        return super().write(vals)
