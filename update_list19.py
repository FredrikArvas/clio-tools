import odoo
from odoo import api, SUPERUSER_ID
odoo.tools.config.parse_config([
    '--config=/opt/odoo19/config/odoo.conf',
    '--db_host=db', '--db_user=odoo', '--db_password=odoo19test',
])
registry = odoo.registry('examensbyran')
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.module.module'].update_list()
    mod = env['ir.module.module'].search([('name','=','examensbyran_funeral_insurance')])
    print('Found:', len(mod), '| state:', mod.state if mod else 'NOT IN DB')
    cr.commit()
