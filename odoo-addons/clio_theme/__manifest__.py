{
    'name': 'Clio Theme',
    'version': '19.0.1.1.0',
    'summary': 'Färgkodad navbar per databas med konfigurerbar färgväljare',
    'author': 'Arvas International AB',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'views/theme_config_views.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'clio_theme/static/src/js/theme_detector.js',
            'clio_theme/static/src/scss/theme.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
