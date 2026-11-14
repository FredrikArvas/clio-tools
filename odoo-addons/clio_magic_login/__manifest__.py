{
    'name': 'Clio Magic Login',
    'version': '19.0.1.0.0',
    'summary': 'Signup-first portal login with magic link authentication',
    'description': 'Shows signup form first on the login page. Portal users log in via a magic link sent to their email instead of a password.',
    'category': 'Authentication',
    'depends': ['auth_signup'],
    'data': [
        'data/mail_template.xml',
        'views/templates.xml',
    ],
    'license': 'AGPL-3',
    'auto_install': False,
    'installable': True,
}
