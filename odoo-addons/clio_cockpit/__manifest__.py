{
    "name":        "Clio Cockpit",
    "version":     "17.0.1.0.0",
    "category":    "Extra Tools",
    "summary":     "Samlad kontrollpanel för alla clio-agenter — mail, RAG, bibliotek, status.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "license":     "LGPL-3",
    "depends":     ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/clio_cockpit_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application":  False,
}
