{
    "name":        "Clio Mail Admin",
    "version":     "18.0.1.0.0",
    "category":    "Extra Tools",
    "summary":     "Admin-panel för clio-agent-mail — kör kommandon direkt från Odoo.",
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
