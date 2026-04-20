{
    "name":        "Clio Graph — Nätverksrelationer",
    "version":     "17.0.1.0.0",
    "category":    "Extra Tools",
    "summary":     "Extends partner_multi_relation with Neo4j sync flags and seeds GSF relation types.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "license":     "LGPL-3",
    "depends":     ["partner_multi_relation", "contacts"],
    "data": [
        "security/ir.model.access.csv",
        "data/relation_types.xml",
        "views/res_partner_relation_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application":  False,
}
