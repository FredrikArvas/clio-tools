{
    'name': 'Clio Theme',
    'version': '19.0.1.0.0',
    'summary': 'FÃ¤rgkodad navbar per databas â€” aiab, ssf, test, staging',
    'author': 'Arvas International AB',
    'depends': ['web'],
    'data': [
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
