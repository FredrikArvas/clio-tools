{
    'name': 'SSF CRM — Behörighetsmodell',
    'version': '19.0.1.0.0',
    'summary': 'Grupper, custom fält och record rules för SSF-administratörer.',
    'author': 'Arvas International AB',
    'website': 'https://github.com/FredrikArvas/clio-odoo-addons/tree/19.0/ssf_crm_access',
    'depends': ['contacts', 'base_setup'],
    'data': [
        'security/groups.xml',
        'security/record_rules.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
