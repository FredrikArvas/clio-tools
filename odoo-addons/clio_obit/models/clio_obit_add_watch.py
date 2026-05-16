"""
clio_obit_add_watch.py
Wizard för att lägga till en bevakning utan GEDCOM-fil.
Söker befintlig partner på namn/födelsenamn — skapar ny om den saknas.
"""

from odoo import api, fields, models


class ClioObitAddWatch(models.TransientModel):
    _name        = "clio.obit.add.watch"
    _description = "Clio Obit — Lägg till bevakning"

    # ── Inmatning ─────────────────────────────────────────────────────────────

    fornamn = fields.Char(string="Förnamn", required=True)
    efternamn = fields.Char(string="Efternamn / Födelsenamn", required=True,
                            help="Används för matchning mot dödsannonser.")
    fodelsedatum = fields.Char(
        string = "Födelseuppgift",
        help   = "Fritt format: '1952', 'ca 1952', 'mars 1952', '1952-03-15'. Lämna tomt om okänt.",
    )
    priority = fields.Selection(
        selection=[("viktig",       "Viktig — direkt notis"),
                   ("normal",       "Normal — daglig digest"),
                   ("bra_att_veta", "Bra att veta")],
        string  = "Prioritet",
        default = "normal",
        required= True,
    )
    user_id = fields.Many2one(
        comodel_name = "res.users",
        string       = "Bevakare",
        required     = True,
        default      = lambda self: self.env.user,
    )

    # ── Tillstånd ─────────────────────────────────────────────────────────────

    state = fields.Selection(
        selection = [("draft", "Utkast"), ("done", "Klar")],
        default   = "draft",
    )
    found_partner_id = fields.Many2one("res.partner", readonly=True)
    result_text      = fields.Text(string="Resultat", readonly=True)

    # ── Åtgärd ────────────────────────────────────────────────────────────────

    def action_add(self):
        self.ensure_one()
        full_name   = f"{self.fornamn} {self.efternamn}".strip()
        name_lower  = full_name.lower()

        # 1. Sök befintlig partner på visningsnamn eller födelsenamn.
        # sudo() krävs för att se alla kontakter oavsett åtkomstregler.
        # Söker på fullt namn, födelsenamn, och båda namndelar separat.
        fornamn   = self.fornamn.strip()
        efternamn = self.efternamn.strip()
        partners = self.env["res.partner"].sudo().search([
            ("is_company", "=", False),
            "|", "|", "|",
            ("name",                  "ilike", full_name),
            ("clio_obit_birth_name",  "ilike", full_name),
            "&", ("name", "ilike", fornamn), ("name", "ilike", efternamn),
            "&", ("clio_obit_birth_name", "ilike", fornamn),
                 ("clio_obit_birth_name", "ilike", efternamn),
        ])

        # Välj bästa träff (exakt matchning prioriteras)
        partner = None
        for p in partners:
            if (p.name or "").lower() == name_lower or \
               (p.clio_obit_birth_name or "").lower() == name_lower:
                partner = p
                break
        if not partner and partners:
            partner = partners[0]

        if partner:
            self.found_partner_id = partner
            # Kontrollera om bevakning redan finns
            existing = self.env["clio.obit.watch"].search([
                ("partner_id", "=", partner.id),
                ("user_id",    "=", self.user_id.id),
            ], limit=1)
            if existing:
                msg = (f"⚠️ {partner.name} bevakas redan av "
                       f"{self.user_id.name} (prioritet: {existing.priority}).")
            else:
                self.env["clio.obit.watch"].create({
                    "partner_id": partner.id,
                    "user_id":    self.user_id.id,
                    "priority":   self.priority,
                })
                msg = (f"✅ Bevakning tillagd: {partner.name} "
                       f"→ {self.user_id.name} ({self.priority})\n"
                       f"Befintlig kontakt (id={partner.id}) användes.")
        else:
            # 2. Skapa ny partner
            vals = {
                "name":                 full_name,
                "clio_obit_birth_name": self.efternamn.strip(),
                "is_company":           False,
            }
            if self.fodelsedatum:
                vals["clio_obit_birth_approx"] = self.fodelsedatum.strip()
            partner = self.env["res.partner"].create(vals)
            self.found_partner_id = partner
            self.env["clio.obit.watch"].create({
                "partner_id": partner.id,
                "user_id":    self.user_id.id,
                "priority":   self.priority,
            })
            msg = (f"✅ Ny kontakt skapad och bevakning tillagd:\n"
                   f"{full_name} → {self.user_id.name} ({self.priority})")

        self.write({"state": "done", "result_text": msg})

        return {
            "type":      "ir.actions.act_window",
            "res_model": "clio.obit.add.watch",
            "res_id":    self.id,
            "view_mode": "form",
            "target":    "new",
        }

    def action_open_partner(self):
        """Öppna partnern i ett nytt fönster."""
        self.ensure_one()
        return {
            "type":      "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id":    self.found_partner_id.id,
            "view_mode": "form",
            "target":    "new",
        }
