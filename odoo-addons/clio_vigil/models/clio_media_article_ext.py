from odoo import api, fields, models


class ClioMediaArticleVigilExt(models.Model):
    _inherit = "clio.media.article"

    vigil_item_id = fields.Many2one(
        comodel_name = "clio.vigil.item",
        string       = "Vigil-objekt",
        ondelete     = "set null",
        index        = True,
        help         = "Länk till det underliggande pipeline-objektet i clio.vigil.item.",
    )

    vigil_state = fields.Selection(
        related  = "vigil_item_id.state",
        string   = "Pipeline-status",
        store    = True,
        index    = True,
        readonly = False,  # Skrivbart → kanban drag-drop fungerar (write-through till vigil_item_id.state)
    )

    vigil_notified_at = fields.Datetime(
        related  = "vigil_item_id.notified_at",
        string   = "Skickad i digest",
        store    = True,
        index    = True,
        readonly = True,
    )

    vigil_notified_date = fields.Char(
        string  = "Skickad (datum)",
        compute = "_compute_vigil_notified_date",
        store   = True,
        index   = True,
    )

    supadata_url = fields.Char(
        string = "Supadata URL",
        help   = "Den Supadata-endpoint som användes för att hämta transkriptet.",
    )

    @api.depends("vigil_notified_at")
    def _compute_vigil_notified_date(self):
        for rec in self:
            if rec.vigil_notified_at:
                rec.vigil_notified_date = rec.vigil_notified_at.strftime("%Y-%m-%d")
            else:
                rec.vigil_notified_date = False

    @api.depends("vigil_item_id")
    def _compute_audio_downloaded(self):
        for rec in self:
            item = rec.vigil_item_id
            rec.audio_downloaded = bool(item and item.archive_path)

    audio_downloaded = fields.Boolean(
        string  = "Nedladdad",
        compute = "_compute_audio_downloaded",
        store   = True,
    )

    def action_boost_vigil(self):
        """Delegerar till det underliggande clio.vigil.item:s action_boost()."""
        self.ensure_one()
        if not self.vigil_item_id:
            return
        return self.vigil_item_id.action_boost()

    def action_requeue_vigil(self):
        """Återkö: sätt vigil_state = queued (write-through till vigil_item_id.state).
        Pipelinen synkar SQLite vid nästa körning via pull_state_changes."""
        self.filtered("vigil_item_id").write({"vigil_state": "queued"})

    # ── Återpubliceringsdetektering ────────────────────────────────────────

    canonical_article_id = fields.Many2one(
        comodel_name = "clio.media.article",
        string       = "Kanonisk version (original)",
        index        = True,
        ondelete     = "set null",
        help         = "Pekar på originalposten om detta är en återpublicering. "
                       "Null = original eller okänt.",
    )

    repub_note = fields.Char(
        string = "Återpubliceringskälla",
        help   = "Fritext om ursprungskällan, t.ex. 'Exopolitics via Multiverse 5D'.",
    )

    repub_count = fields.Integer(
        string  = "Antal återpubliceringar",
        compute = "_compute_repub_count",
        store   = False,
        help    = "Hur många andra poster pekar på denna som original. "
                  "Hög siffra = brett spridet avsnitt.",
    )

    def _compute_repub_count(self):
        # Räknar live via SQL för prestanda — ingen @api.depends behövs eftersom
        # store=False alltid triggar om (inga cache-problem med det inversa fältet).
        if not self.ids:
            return
        self.env.cr.execute(
            """
            SELECT canonical_article_id, COUNT(*) AS cnt
            FROM clio_media_article
            WHERE canonical_article_id = ANY(%s)
            GROUP BY canonical_article_id
            """,
            (list(self.ids),),
        )
        counts = dict(self.env.cr.fetchall())
        for rec in self:
            rec.repub_count = counts.get(rec.id, 0)
