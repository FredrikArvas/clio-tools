{
    'name': 'Clio Vigil â€” Mediebevakning',
    'version': '19.0.1.0.0',
    'summary': 'Odoo-vy fÃ¶r clio-vigil: kÃ¤llor, pipeline-kÃ¶ och fÃ¤rdiga bevakningsobjekt',
    'author': 'Arvas International AB',
    'depends': ['contacts', 'clio_cockpit'],
    'data': [
        'security/ir.model.access.csv',
        'views/clio_vigil_source_views.xml',
        'views/clio_vigil_item_views.xml',
        'views/clio_vigil_subscriber_views.xml',
        'views/clio_vigil_wizard_views.xml',
        'views/clio_vigil_pipeline_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
