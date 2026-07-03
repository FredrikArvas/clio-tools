from odoo import models, fields, api


class UapSeries(models.Model):
    _name        = "uap.series"
    _description = "UAP — Event Series"
    _order       = "date_start desc"
    _rec_name    = "name"

    name = fields.Char(string="Series Name", required=True)

    series_type = fields.Selection(
        selection=[
            ("wave",            "Wave — Wide area, many encounters"),
            ("swarm",           "Swarm — Concentrated area, dense"),
            ("recurring",       "Recurring — Same location, repeated"),
            ("single_extended", "Single Extended Event — Multi-day"),
            ("campaign",        "Campaign — Investigation focus"),
        ],
        string="Series Type",
        index=True,
    )

    # --- Tid ---
    date_start = fields.Date(string="Start Date")
    date_end   = fields.Date(string="End Date")

    # --- Geografi ---
    geo_lat     = fields.Float(string="Center Latitude",  digits=(10, 6))
    geo_lng     = fields.Float(string="Center Longitude", digits=(10, 6))
    bbox_km     = fields.Float(
        string="Radius (km)",
        help="Ungefärlig radie för serien i kilometer",
    )
    country_ids = fields.Many2many("res.country", string="Countries")

    # --- Pipeline ---
    confidence = fields.Float(
        string="Confidence",
        digits=(3, 2),
        help="0.0–1.0, satt av detekteringsalgoritmen",
    )
    status = fields.Selection(
        selection=[
            ("auto_pending",   "Auto — Pending Review"),
            ("auto_confirmed", "Auto — Confirmed"),
            ("confirmed",      "Manually Confirmed"),
            ("rejected",       "Rejected"),
        ],
        string="Status",
        default="auto_pending",
        index=True,
    )

    # --- Relationer ---
    encounter_ids = fields.One2many(
        "uap.encounter",
        "series_id",
        string="Encounters",
    )
    encounter_count = fields.Integer(
        string="# Encounters",
        compute="_compute_encounter_count",
        store=False,
    )
    notes = fields.Text(string="Notes")

    @api.depends("encounter_ids")
    def _compute_encounter_count(self):
        for rec in self:
            rec.encounter_count = len(rec.encounter_ids)

    def action_open_encounters(self):
        self.ensure_one()
        return {
            "type":     "ir.actions.act_window",
            "name":     f"Encounters — {self.name}",
            "res_model":"uap.encounter",
            "view_mode":"list,form",
            "domain":   [("series_id", "=", self.id)],
            "context":  {"default_series_id": self.id},
        }

    def action_confirm(self):
        for rec in self:
            rec.status = "confirmed"

    def action_reject(self):
        for rec in self:
            rec.status = "rejected"
