{
    "name":     "Clio â€” E-postbehÃ¶righeter",
    "version":  "19.0.1.0.0",
    "summary":  "BehÃ¶righetshantering fÃ¶r clio-agent-mail med tvÃ¥vÃ¤gssynk",
    "depends":  ["base", "clio_mail_admin"],
    "application": False,
    "data": [
        "security/ir.model.access.csv",
        "views/clio_mail_permission_views.xml",
    ],
}
