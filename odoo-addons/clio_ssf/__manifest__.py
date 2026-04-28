{
    'name': 'Clio SSF — Installationsprofil',
    'version': '18.0.2.0.0',
    'summary': 'Meta-modul: installerar alla Clio-moduler för SSF-databasen',
    'author': 'Arvas International AB',
    'depends': [
        'clio_cockpit',
        'clio_discuss',
        'clio_graph',
        'clio_mail_admin',
        'clio_theme',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
