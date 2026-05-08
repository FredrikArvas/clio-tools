{
    'name': 'Clio Event Log',
    'version': '18.0.1.0.0',
    'summary': 'Logg över inkommande mail-händelser från clio-agent-mail (intent-klassificering, PII, blockeringar)',
    'author': 'Arvas International AB',
    'category': 'Clio',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/clio_event_log_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
