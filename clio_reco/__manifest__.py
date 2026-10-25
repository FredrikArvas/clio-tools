{
    'name': 'Clio Reco — Rekommendationer',
    'version': '19.0.1.0.0',
    'summary': 'Bok-, film- och länkrekommendationer med betyg och smaktvilling-algoritm',
    'author': 'Arvas International AB',
    'website': 'https://github.com/FredrikArvas/clio-tools/tree/19.0/clio_reco',
    'license': 'LGPL-3',
    'category': 'Extra Tools',
    'depends': ['base', 'mail', 'website', 'portal'],
    'data': [
        'security/clio_reco_security.xml',
        'security/ir.model.access.csv',
        'views/genre_views.xml',
        'views/item_views.xml',
        'views/menu.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
