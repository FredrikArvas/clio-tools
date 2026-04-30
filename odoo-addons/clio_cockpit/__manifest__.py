{
    "name":        "Clio Cockpit",
    "version":     "18.0.4.0.0",
    "category":    "Extra Tools",
    "summary":     "Samlad kontrollpanel för alla clio-agenter — flik-design med behörighetsstyrning.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "license":     "LGPL-3",
    "depends":     ["base"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/clio_cockpit_views.xml",
        "views/clio_db_size_views.xml",
        "views/clio_tool_heartbeat_views.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "clio_cockpit/static/src/js/cockpit_enter.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "application":  False,
}
