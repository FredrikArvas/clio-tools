{
    'name': 'Clio Event Log',
    'version': '19.0.1.0.0',
    'summary': 'Logg Ã¶ver inkommande mail-hÃ¤ndelser frÃ¥n clio-agent-mail (intent-klassificering, PII, blockeringar)',
    'author': 'Arvas International AB',
    'category': 'Clio',
    'depends': ['base', 'clio_mail_admin'],
    'data': [
        'security/ir.model.access.csv',
        'views/clio_event_log_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
