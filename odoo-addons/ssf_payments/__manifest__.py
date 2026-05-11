{
    "name": "SSF - Betalningar",
    "version": "19.0.1.0.0",
    "summary": "Startavgiftsbetalningar (Payments) synkade frÃ¥n SSFTA.",
    "author": "Arvas International AB",
    "depends": ["ssf_competition"],
    "data": [
        "security/ir.model.access.csv",
        "views/ssf_payment_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
