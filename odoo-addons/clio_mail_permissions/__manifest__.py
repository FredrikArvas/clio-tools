{
    "name":     "Clio — E-postbehörigheter",
    "version":  "18.0.1.0.0",
    "summary":  "Behörighetshantering för clio-agent-mail med tvåvägssynk",
    "depends":  ["base", "clio_mail_admin"],
    "application": False,
    "data": [
        "security/ir.model.access.csv",
        "views/clio_mail_permission_views.xml",
    ],
}
