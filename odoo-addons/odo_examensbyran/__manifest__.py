{
    'name': 'Examensbyrån — Installationsprofil',
    'version': '18.0.1.0.0',
    'summary': 'Meta-modul: installerar clio_obit + svenska lokaliseringar för Examensbyrån',
    'author': 'Arvas International AB',
    'license': 'LGPL-3',
    'depends': [
        'clio_obit',
        'l10n_se_ssn',
        'l10n_se_partner',
        'website',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
}
