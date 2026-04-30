import logging

_logger = logging.getLogger(__name__)

EXAMENSBYRAN_USERS = [
    {'name': 'Fredrik Arvas', 'login': 'fredrik@arvas.se', 'email': 'fredrik@arvas.se', 'admin': True},
]


def post_init_hook(env):
    _install_swedish(env)
    _create_users(env)


def _install_swedish(env):
    lang = env['res.lang'].with_context(active_test=False).search([('code', '=', 'sv_SE')])
    if lang and not lang.active:
        lang.active = True
    elif not lang:
        env['res.lang'].load_lang('sv_SE')
    env['base.language.install'].create({
        'lang_ids': env['res.lang'].search([('code', '=', 'sv_SE')]).ids,
        'overwrite': False,
    }).lang_install()
    env['res.users'].search([
        ('active', '=', True), ('share', '=', False)
    ]).mapped('partner_id').write({'lang': 'sv_SE'})
    _logger.info('odo_examensbyran: svenska installerat')


def _create_users(env):
    group_system = env.ref('base.group_system')
    group_user = env.ref('base.group_user')
    for u in EXAMENSBYRAN_USERS:
        if env['res.users'].search([('login', '=', u['login'])]):
            _logger.info('odo_examensbyran: %s finns redan, hoppar över', u['login'])
            continue
        group = group_system if u['admin'] else group_user
        env['res.users'].with_context(no_reset_password=True).create({
            'name': u['name'],
            'login': u['login'],
            'email': u['email'],
            'lang': 'sv_SE',
            'groups_id': [(6, 0, [group.id])],
        })
        _logger.info('odo_examensbyran: skapade användare %s', u['login'])
