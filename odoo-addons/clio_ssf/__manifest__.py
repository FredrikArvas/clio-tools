{
    'name': 'Clio SSF â€” Installationsprofil',
    'version': '19.0.4.0.0',
    'summary': 'Meta-modul: installerar alla Clio-moduler fÃ¶r SSF-databasen',
    'author': 'Arvas International AB',
    'depends': [
        'clio_cockpit',
        'clio_discuss',
        'clio_graph',
        'clio_mail_admin',
        'clio_theme',
        'l10n_se_ssn',
        'l10n_se_partner',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}