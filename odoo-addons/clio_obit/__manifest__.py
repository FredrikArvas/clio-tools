{
    "name":        "Clio Obit — Dödsannonsbevakning",
    "version":     "18.0.1.0.0",
    "category":    "Extra Tools",
    "summary":     "Extends res.partner with obituary watch fields and family relation tracking.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "license":     "LGPL-3",
    "depends":     ["contacts"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application":  False,
}
