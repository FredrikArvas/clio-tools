{
    "name":        "Clio Interview",
    "version":     "18.0.1.0.0",
    "category":    "Extra Tools",
    "summary":     "Cockpit för Claude-drivna intervjuer via e-post — mallar, sessioner och sammanfattningar.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "license":     "LGPL-3",
    "depends":     ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/clio_interview_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application":  True,
}
