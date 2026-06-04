import os
import secrets
import logging

_logger = logging.getLogger(__name__)

SSF_USERS = [
    {'name': 'Fredrik Arvas', 'login': 'fredrik@arvas.se',           'email': 'fredrik@arvas.se',           'admin': True},
    {'name': 'Maria Nyberg',  'login': 'maria.nyberg@capgemini.com', 'email': 'maria.nyberg@capgemini.com', 'admin': False},
    {'name': 'Carl Lindell',  'login': 'carl.lindell@capgemini.com', 'email': 'carl.lindell@capgemini.com', 'admin': False},
]


def post_init_hook(env):
    _install_swedish(env)
    _create_ssf_users(env)
    _setup_user_passwords(env)


def _setup_user_passwords(env):
    admin_password = os.environ.get('ARVAS_ADMIN_PASSWORD', '')

    # Fredrik — use env password or generate one
    fredrik = env['res.users'].search([('login', '=', 'fredrik@arvas.se')], limit=1)
    if fredrik:
        if admin_password:
            fredrik.password = admin_password
            _logger.info('clio_ssf: lösenord satt för fredrik@arvas.se från ARVAS_ADMIN_PASSWORD')
        else:
            generated = secrets.token_urlsafe(14)
            fredrik.password = generated
            _logger.warning('clio_ssf: ARVAS_ADMIN_PASSWORD ej satt — genererat lösenord för fredrik@arvas.se: %s', generated)

    # admin — sätt alltid slumpmässigt lösenord (ta bort admin/admin-risken)
    admin = env['res.users'].search([('login', '=', 'admin')], limit=1)
    if admin:
        admin_random = secrets.token_urlsafe(14)
        admin.password = admin_random
        _logger.warning('clio_ssf: admin-kontots lösenord randomiserat: %s', admin_random)


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
    _logger.info('clio_ssf: svenska installerat och satt pa alla anvandare')


def _create_ssf_users(env):
    group_system = env.ref('base.group_system')
    group_user = env.ref('base.group_user')
    for u in SSF_USERS:
        if env['res.users'].search([('login', '=', u['login'])]):
            _logger.info('clio_ssf: %s finns redan, hoppar over', u['login'])
            continue
        group = group_system if u['admin'] else group_user
        env['res.users'].with_context(no_reset_password=True).create({
            'name': u['name'],
            'login': u['login'],
            'email': u['email'],
            'lang': 'sv_SE',
            'group_ids': [(6, 0, [group.id])],
        })
        _logger.info('clio_ssf: skapade anvandare %s', u['login'])
