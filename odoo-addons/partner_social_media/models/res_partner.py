from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    social_linkedin = fields.Char('LinkedIn', tracking=True)
    social_twitter = fields.Char('X / Twitter', tracking=True)
    social_facebook = fields.Char('Facebook', tracking=True)
    social_instagram = fields.Char('Instagram', tracking=True)
    social_github = fields.Char('GitHub', tracking=True)
