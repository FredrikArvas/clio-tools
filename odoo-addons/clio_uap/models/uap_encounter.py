import uuid
from odoo import models, fields


class UapEncounter(models.Model):
    _name        = "uap.encounter"
    _description = "UAP — Encounter"
    _order       = "date_observed desc, encounter_id"
    _rec_name    = "title_en"

    encounter_id = fields.Char(
        string="Encounter ID",
        required=True,
        index=True,
        help="Unikt text-ID, t.ex. SWE_PPXL_0001",
    )
    encounter_guid = fields.Char(
        string="GUID",
        readonly=True,
        default=lambda self: str(uuid.uuid4()),
        copy=False,
    )

    # --- Tid & plats ---
    date_observed = fields.Datetime(string="Date Observed")
    country_id = fields.Many2one(
        comodel_name="res.country",
        string="Country",
        index=True,
    )
    location = fields.Text(string="Location")

    # --- Titlar ---
    title_en = fields.Char(string="Title (EN)")
    title_original = fields.Char(string="Title (Original)")

    # --- Beskrivningar ---
    description_en = fields.Text(string="Description (EN)")
    description_sv = fields.Text(string="Description (SV)")
    description_original = fields.Text(string="Description (Original)")
    language_original = fields.Selection(
        selection=[
            ("en",    "English"),
            ("sv",    "Swedish"),
            ("pt",    "Portuguese"),
            ("es",    "Spanish"),
            ("fr",    "French"),
            ("de",    "German"),
            ("ja",    "Japanese"),
            ("other", "Other"),
        ],
        string="Original Language",
    )

    # --- Klassificering ---
    encounter_class = fields.Selection(
        selection=[
            ("1", "1 — Sighting"),
            ("2", "2 — Close Encounter"),
            ("3", "3 — Physical Evidence"),
            ("4", "4 — Abduction / Contact"),
        ],
        string="Encounter Class",
        index=True,
    )
    discourse_level = fields.Selection(
        selection=[
            ("1", "1 — Fringe / Unknown"),
            ("2", "2 — Limited Public Awareness"),
            ("3", "3 — Active Public Debate"),
            ("4", "4 — Official Acknowledgement"),
            ("5", "5 — Confirmed / Declassified"),
        ],
        string="Discourse Level",
        index=True,
    )
    official_response = fields.Selection(
        selection=[
            ("A", "A — No Response"),
            ("B", "B — Denial"),
            ("C", "C — Acknowledgement"),
            ("D", "D — Investigation"),
            ("E", "E — Confirmation"),
        ],
        string="Official Response",
    )
    status = fields.Selection(
        selection=[
            ("pending",  "Pending Review"),
            ("verified", "Verified"),
            ("archived", "Archived"),
        ],
        string="Status",
        default="pending",
        index=True,
    )

    # --- Relationer ---
    source_ids = fields.Many2many(
        comodel_name="uap.source",
        relation="uap_encounter_source_rel",
        column1="encounter_id_col",
        column2="source_id_col",
        string="Sources",
    )
    witness_ids = fields.Many2many(
        comodel_name="uap.witness",
        relation="uap_encounter_witness_rel",
        column1="encounter_id_col",
        column2="witness_id_col",
        string="Witnesses",
    )
    verification_ids = fields.One2many(
        comodel_name="uap.verification",
        inverse_name="encounter_id",
        string="Verification Log",
    )

    # --- Övrigt ---
    research_notes = fields.Text(string="Research Notes")
    neo4j_node_id = fields.Char(string="Neo4j Node ID", readonly=True, copy=False)

    # --- Computed counts för smartbuttons ---
    source_count = fields.Integer(
        string="# Sources",
        compute="_compute_counts",
        store=False,
    )
    witness_count = fields.Integer(
        string="# Witnesses",
        compute="_compute_counts",
        store=False,
    )
    verification_count = fields.Integer(
        string="# Verifications",
        compute="_compute_counts",
        store=False,
    )

    def _compute_counts(self):
        for rec in self:
            rec.source_count = len(rec.source_ids)
            rec.witness_count = len(rec.witness_ids)
            rec.verification_count = len(rec.verification_ids)
