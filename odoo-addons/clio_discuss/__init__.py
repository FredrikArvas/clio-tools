import secrets
from . import models


def post_init_hook(env):
    """
    Skapar Clio Bot-användaren och sparar lösenordet i System Parameters.
    Körs en gång vid installation — lösenordet läses sedan av clio-agent-odoo.
    """
    existing = env['res.users'].search([('login', '=', 'clio-bot')], limit=1)
    if existing:
        return

    password = secrets.token_urlsafe(32)

    partner = env.ref('clio_discuss.partner_clio_bot')
    user = env['res.users'].create({
        'name': 'Clio',
        'login': 'clio-bot',
        'email': 'clio-bot@arvas.se',
        'partner_id': partner.id,
        'groups_id': [(4, env.ref('base.group_user').id)],
    })
    user.password = password

    env['ir.config_parameter'].sudo().set_param(
        'clio_discuss.bot_password', password
    )
    env['ir.config_parameter'].sudo().set_param(
        'clio_discuss.bot_login', 'clio-bot'
    )
