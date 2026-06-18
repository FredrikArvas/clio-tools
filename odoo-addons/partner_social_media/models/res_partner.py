from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    social_linkedin = fields.Char('LinkedIn')
    social_twitter = fields.Char('X / Twitter')
    social_facebook = fields.Char('Facebook')
    social_instagram = fields.Char('Instagram')
    social_github = fields.Char('GitHub')
