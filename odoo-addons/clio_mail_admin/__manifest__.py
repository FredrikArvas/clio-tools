{
    "name":        "Clio Mail Admin",
    "version":     "19.0.2.0.0",
    "category":    "Extra Tools",
    "summary":     "Admin-panel för clio-agent-mail — kör kommandon direkt från Odoo.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "website":     "https://github.com/FredrikArvas/clio-odoo-addons/tree/19.0/clio_mail_admin",
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
