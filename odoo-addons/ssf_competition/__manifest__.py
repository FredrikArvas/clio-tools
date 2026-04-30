{
    "name": "SSF - Competition Module",
    "version": "18.0.1.10.0",
    "summary": "SSF competition data (Events, Competitions, Results) synced from SSFTA.",
    "author": "Arvas International AB",
    "depends": ["contacts"],
    "data": [
        "security/ir.model.access.csv",
        "views/ssf_sector_views.xml",
        "views/ssf_event_views.xml",
        "views/ssf_competition_views.xml",
        "views/ssf_ccd_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}