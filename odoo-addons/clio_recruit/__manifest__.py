{
    "name":        "Clio Recruit — Passiv kandidatsourcing",
    "version":     "19.0.1.0.0",
    "category":    "Extra Tools",
    "summary":     "Odoo-vy för clio-recruiter: rekryterarprofiler och matchhistorik.",
    "author":      "Arvas International AB",
    "website":     "https://github.com/FredrikArvas/clio-odoo-addons/tree/19.0/clio_recruit",
    "license":     "LGPL-3",
    "depends":     ["contacts", "clio_cockpit"],
    "data": [
        "security/ir.model.access.csv",
        "views/clio_recruiter_profile_views.xml",
        "views/clio_recruiter_match_views.xml",
        "views/menu.xml",
    ],
    "installable":  True,
    "auto_install": False,
    "application":  False,
}
