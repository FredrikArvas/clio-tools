"""
clio_vigil_item.py
Pipeline-objekt: artiklar, podcastavsnitt och YouTube-klipp som passerar
genom clio-vigils bearbetningskedja (filter → transkription → RAG → digest).
Speglar vigil_items-tabellen i SQLite.
"""

from __future__ import annotations

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ClioVigilItem(models.Model):
    _name        = "clio.vigil.item"
    _description = "Clio Vigil — Bevakningsobjekt"
    _order       = "priority_score desc, published_at desc"
    _rec_name    = "title"

    # ── Identifiering ────────────────────────────────────────────────────────

    url = fields.Char(
        string   = "URL",
        required = True,
        index    = True,
        copy     = False,
    )
    title = fields.Char(string="Titel")

    # ── Källmetadata ─────────────────────────────────────────────────────────

    domain = fields.Selection(
        selection = [("ufo", "UFO/UAP"), ("ai", "AI-modeller")],
        string    = "Domän",
        index     = True,
    )
    source_type = fields.Selection(
        selection = [("rss", "RSS"), ("youtube", "YouTube"), ("web", "Webb")],
        string    = "Källtyp",
    )
    source_name = fields.Char(string="Källa", index=True)
    source_id = fields.Many2one(
        comodel_name = "clio.vigil.source",
        string       = "Källpost",
        index        = True,
        ondelete     = "set null",
        help         = "Länk till källans Odoo-post. Sätts vid import; "
                       "language ärvs härifrån om fältet saknas.",
    )
    source_maturity = fields.Selection(
        selection = [
            ("tidig",     "Tidig källa"),
            ("etablerad", "Etablerad"),
            ("akademisk", "Akademisk"),
        ],
        string = "Mognad",
    )
    published_at = fields.Datetime(
        string = "Publicerat",
        index  = True,
    )
    duration_seconds = fields.Integer(
        string = "Längd (s)",
        help   = "Längd i sekunder. Tomt för webb/PDF.",
    )

    # ── Poäng och prioritet ──────────────────────────────────────────────────

    relevance_score = fields.Float(
        string = "Relevansscore",
        digits = (5, 4),
        help   = "0.0–1.0 från nyckelordsfiltret.",
    )
    priority_score = fields.Float(
        string = "Prioritet",
        digits = (5, 4),
        index  = True,
        help   = "Relevansscore × källvikt × längdfaktor × tidsfaktor.",
    )

    # ── Tillstånd ────────────────────────────────────────────────────────────

    state = fields.Selection(
        selection = [
            ("discovered",  "Hittad"),
            ("filtered_in", "Passerade filter"),
            ("filtered_out","Filtrerades bort"),
            ("queued",      "I kö"),
            ("transcribing","Transkriberas"),
            ("transcribed", "Transkriberad"),
            ("captioned",   "Auto-textad (YouTube)"),  # Sprint B
            ("indexed",     "Indexerad"),
            ("notified",    "Skickad i digest"),
        ],
        string  = "Tillstånd",
        default = "discovered",
        index   = True,
    )

    # ── Innehåll ─────────────────────────────────────────────────────────────

    summary = fields.Text(
        string = "Sammanfattning",
        help   = "2–3 meningar från Claude API.",
    )
    transcript_snippet = fields.Text(
        string = "Transkript (utdrag)",
        help   = "Första 500 tecken av transkriptionen.",
    )

    # ── Språk ────────────────────────────────────────────────────────────────

    language = fields.Selection(
        selection = [
            ("en",    "Engelska"),
            ("sv",    "Svenska"),
            ("pt",    "Portugisiska"),
            ("other", "Annat"),
        ],
        string = "Språk",
        index  = True,
        help   = "Ärvs från källans grundspråk. "
                 "Transkriptionen kan korrigera fältet om detekterat språk avviker.",
    )

    # ── Podcast-taggar ────────────────────────────────────────────────────────

    podcast_format = fields.Selection(
        selection = [
            ("interview",    "Intervju"),
            ("monologue",    "Monolog"),
            ("panel",        "Paneldiskussion"),
            ("documentary",  "Dokumentär"),
            ("other",        "Övrigt"),
        ],
        string = "Podcastformat",
    )
    podcast_topic = fields.Selection(
        selection = [
            ("contact",      "Kontaktupplevelse"),
            ("sighting",     "Observationserfarenhet"),
            ("abduction",    "Bortförande/MILAB"),
            ("disclosure",   "Disclosure / officiellt"),
            ("physics",      "Fysik / teknik"),
            ("spirituality", "Andlighet / medvetande"),
            ("news",         "Nyheter"),
            ("other",        "Övrigt"),
        ],
        string = "Ämne",
    )
    podcast_witness_score = fields.Float(
        string = "Vittnespoäng",
        digits = (5, 2),
        help   = "0–10: trovärdighet och detaljrikedom hos vittnet/gästen.",
    )
    podcast_keep = fields.Boolean(
        string  = "Bevara",
        default = False,
        help    = "Markerat av taggaren: avsnittet är värt att transkribera.",
    )
    podcast_geo_ids = fields.Many2many(
        comodel_name = "clio.podcast.geo",
        relation     = "clio_vigil_item_geo_rel",
        column1      = "item_id",
        column2      = "geo_id",
        string       = "Geografiska platser",
    )
    podcast_background_ids = fields.Many2many(
        comodel_name = "clio.podcast.background",
        relation     = "clio_vigil_item_bg_rel",
        column1      = "item_id",
        column2      = "bg_id",
        string       = "Vittnesbakgrunder",
    )

    # ── Sprint C: Arkivering ─────────────────────────────────────────────────

    archive_downloaded = fields.Boolean(
        string  = "Arkiverad",
        default = False,
        help    = "Episoden finns nedladdad lokalt på servern.",
    )
    archive_path = fields.Char(
        string = "Lokal sökväg",
        help   = "Absolut sökväg till den nedladdade filen på servern.",
    )

    # ── Tidsstämplar ─────────────────────────────────────────────────────────

    created_at  = fields.Datetime(string="Skapad",       copy=False)
    notified_at = fields.Datetime(string="Notifierad",   copy=False)

    _url_uniq = models.Constraint(
        "UNIQUE(url)",
        "Objekt-URL måste vara unik.",
    )

    # ── Odoo-standard: språkärv från källpost ────────────────────────────────

    @api.onchange("source_id")
    def _onchange_source_id(self):
        """Fyller i språk automatiskt när källpost väljs i formuläret."""
        if self.source_id and not self.language:
            src_lang = self.source_id.language
            # Mappa källans "multi" till False (okänt på avsnittsnivå — vänta på transkription)
            self.language = src_lang if src_lang != "multi" else False

    @api.model_create_multi
    def create(self, vals_list):
        """Ärvt källspråk vid massskapning om language saknas och source_id finns."""
        for vals in vals_list:
            if not vals.get("language") and vals.get("source_id"):
                src = self.env["clio.vigil.source"].browse(vals["source_id"])
                if src.language and src.language != "multi":
                    vals["language"] = src.language
        return super().create(vals_list)

    # ── Åtgärder ─────────────────────────────────────────────────────────────

    def action_boost(self):
        """Boostar objektet till toppen av transkriptionskön (prio 999)."""
        self.ensure_one()
        self.write({
            "priority_score": 999.0,
            "state": "queued",
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Boostade!",
                "message": f"'{self.title or self.url[:60]}' boostad till toppen av kön.",
                "type": "success",
                "sticky": False,
            },
        }

    def action_reset_to_discovered(self):
        """Återställer objektet till discovered (börja om)."""
        self.ensure_one()
        self.write({
            "state": "discovered",
            "priority_score": 0.0,
        })
