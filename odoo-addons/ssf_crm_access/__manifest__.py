{
    'name': 'SSF CRM â€” BehÃ¶righetsmodell',
    'version': '19.0.1.0.0',
    'summary': 'Grupper, custom fÃ¤lt och record rules fÃ¶r SSF-administratÃ¶rer.',
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
