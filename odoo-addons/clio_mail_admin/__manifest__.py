{
    "name":        "Clio Mail Admin",
    "version":     "19.0.2.0.0",
    "category":    "Extra Tools",
    "summary":     "Admin-panel fÃ¶r clio-agent-mail â€” kÃ¶r kommandon direkt frÃ¥n Odoo.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "license":     "LGPL-3",
    "depends":     ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/clio_mail_admin_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application":  False,
}
