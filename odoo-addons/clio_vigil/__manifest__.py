{
    'name': 'Clio Vigil — Mediebevakning',
    'version': '18.0.1.0.0',
    'summary': 'Odoo-vy för clio-vigil: källor, pipeline-kö och färdiga bevakningsobjekt',
    'author': 'Arvas International AB',
    'depends': ['contacts', 'clio_cockpit'],
    'data': [
        'security/ir.model.access.csv',
        'views/clio_vigil_source_views.xml',
        'views/clio_vigil_item_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
