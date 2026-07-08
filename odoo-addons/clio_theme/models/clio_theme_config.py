from odoo import api, fields, models


class ClioThemeConfig(models.Model):
    _name = 'clio.theme.config'
    _description = 'Clio Theme Configuration'
    _rec_name = 'id'

    navbar_bg     = fields.Char('Navbar bakgrund',     placeholder='#2A3F6F')
    navbar_border = fields.Char('Navbar accent/linje', placeholder='#C8A84B')
    navbar_text   = fields.Char('Navbar text',         placeholder='#ffffff')
    sidebar_bg    = fields.Char('Sidebar bakgrund',    placeholder='#1a1a2e')
    sidebar_text  = fields.Char('Sidebar text',        placeholder='#ffffff')
    primary_color = fields.Char('Primär accentfärg',   placeholder='#2A3F6F')

    @api.model
    def get_config(self):
        return self.sudo().search([], limit=1)
