# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    _install_swedish(env)


def _install_swedish(env):
    """Aktivera och installera svenska (sv_SE) som systemspråk."""
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
    _logger.info('odoo_aiab: svenska installerat och satt på alla interna användare')
