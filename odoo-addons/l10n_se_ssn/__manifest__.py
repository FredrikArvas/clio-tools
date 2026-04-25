{
    "name":        "Sweden — Personnummer (SSN)",
    "version":     "18.0.1.0.0",
    "category":    "Localization",
    "summary":     "Lägger till personnummer (SSN) på res.partner med Luhn-validering.",
    "author":      "Fredrik Arvas / Arvas International AB",
    "license":     "LGPL-3",
    "depends":     ["contacts"],
    "data": [
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application":  False,
}
