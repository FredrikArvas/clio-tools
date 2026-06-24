{
    'name': 'Clio Lobbying — PR och Mediarelationer',
    'version': '18.0.1.0.0',
    'summary': 'Journalist-databas, pitch-hantering och mediarelationer för Clio Lobbying',
    'author': 'Arvas International AB',
    'depends': ['contacts', 'clio_vigil'],
    'data': [
        'security/ir.model.access.csv',
        'views/clio_lobbying_journalist_views.xml',
        'views/clio_lobbying_event_views.xml',
        'views/clio_lobbying_pitch_views.xml',
        'views/res_partner_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
