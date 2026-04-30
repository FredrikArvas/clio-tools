{
    "name": "SSF - LOK-stöd",
    "version": "18.0.1.0.0",
    "summary": "LOK-stödsrapporter (FeeReports) synkade från SSFTA.",
    "author": "Arvas International AB",
    "depends": ["ssf_competition"],
    "data": [
        "security/ir.model.access.csv",
        "views/ssf_fee_report_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
