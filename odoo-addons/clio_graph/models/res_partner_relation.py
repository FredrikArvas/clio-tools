"""
res_partner_relation.py
Utökar res.partner.relation (från OCA partner_multi_relation) med Neo4j-synkflaggor.
"""

from odoo import models, fields


class ResPartnerRelation(models.Model):
    _inherit = "res.partner.relation"

    sync_to_neo4j = fields.Boolean(
        string="Sync to Neo4j",
        default=True,
        help="Markera om denna relation ska speglas till Neo4j-grafsdatabasen.",
    )
    neo4j_synced_at = fields.Datetime(
        string="Last Synced",
        readonly=True,
        help="Tidpunkt när relationen senast skrevs till Neo4j.",
    )
