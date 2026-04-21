{
    'name': 'Clio Discuss',
    'version': '18.0.0.1.0',
    'summary': 'Clio AI-assistent i Odoo Discuss — global #clio-kanal',
    'author': 'Arvas International AB',
    'depends': ['mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/discuss_channel.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
