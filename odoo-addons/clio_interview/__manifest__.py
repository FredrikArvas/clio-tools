{
    "name":        "Clio Interview",
    "version":     "18.0.1.0.0",
    "category":    "Extra Tools",
    "summary":     "Cockpit for Claude-driven interviews via email — templates, sessions and summaries.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "license":     "LGPL-3",
    "depends":     ["base"],
    "data": [
        "security/ir.model.access.csv",
        "data/clio_interview_cron.xml",
        "views/clio_interview_views.xml",
        "views/menu.xml",
    ],
    # translations laddas via Odoo Settings → Translations efter export/import
    "installable": True,
    "auto_install": False,
    "application":  True,
}
