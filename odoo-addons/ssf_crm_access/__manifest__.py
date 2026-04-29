{
    'name': 'SSF CRM — Behörighetsmodell',
    'version': '18.0.1.0.0',
    'summary': 'Grupper, custom fält och record rules för SSF-administratörer.',
    'author': 'Arvas International AB',
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
