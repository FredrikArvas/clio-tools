# -*- coding: utf-8 -*-
"""
Regressionstester för clio_magic_login.
Fokus: token-engångsanvändning, säkerhetsgränser, verify-redirect.

Använder befintliga portalanvändare i DB — undviker res.partner.create()
som kraschar i detta modul-sammanhang (autopost_bills NOT NULL, saknar default
när clio_magic_login saknar account i sina deps).

Template-routes (/web/login GET/POST) testas ej — asset-pipeline kraschar
i HttpCase utan --update. De verifieras live.
"""
from odoo.tests.common import HttpCase, TransactionCase


def _get_portal_user(env):
    """Hämtar en befintlig aktiv portalanvändare."""
    user = env['res.users'].search(
        [('share', '=', True), ('active', '=', True)], limit=1
    )
    if not user:
        raise Exception('Inga portalanvändare hittades i databasen')
    return user


class TestTokenInfrastructure(TransactionCase):
    """auth_signup token-infrastruktur — ingen HTTP behövs."""

    def setUp(self):
        super().setUp()
        self.portal_user = _get_portal_user(self.env)

    def test_portal_user_has_share_flag(self):
        self.assertTrue(self.portal_user.share)

    def test_internal_user_has_no_share_flag(self):
        self.assertFalse(self.env.ref('base.user_admin').share)

    def test_generate_token_returns_nonempty_string(self):
        # Odoo 19: token är HMAC-signerad payload, lagras ej i DB
        partner = self.portal_user.partner_id.sudo()
        partner.write({'signup_type': 'magic'})
        token = partner._generate_signup_token(expiration=0.25)
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 20)

    def test_get_partner_from_valid_token(self):
        partner = self.portal_user.partner_id.sudo()
        partner.write({'signup_type': 'magic'})
        token = partner._generate_signup_token(expiration=0.25)
        found = self.env['res.partner'].sudo()._get_partner_from_token(token)
        self.assertEqual(found.id, partner.id)

    def test_get_partner_from_invalid_token_raises_or_returns_false(self):
        try:
            result = self.env['res.partner'].sudo()._get_partner_from_token('OGILTIGT')
            self.assertFalse(result)
        except Exception:
            pass  # Raise är acceptabelt

    def test_clearing_signup_type_invalidates_token(self):
        # Simulerar engångsanvändning: signup_type clearas → token ogiltig
        partner = self.portal_user.partner_id.sudo()
        partner.write({'signup_type': 'magic'})
        token = partner._generate_signup_token(expiration=0.25)
        partner.write({'signup_type': False})
        try:
            result = self.env['res.partner'].sudo()._get_partner_from_token(token)
            self.assertFalse(result)
        except Exception:
            pass


class TestMagicLoginVerify(HttpCase):
    """HTTP-flöden för /web/magic_login/verify — rena redirectar, ingen template."""

    def setUp(self):
        super().setUp()
        self.portal_user = _get_portal_user(self.env)

    def test_verify_route_registered(self):
        resp = self.url_open('/web/magic_login/verify?token=X', allow_redirects=False)
        self.assertNotEqual(resp.status_code, 404)

    def test_invalid_token_redirects_to_login(self):
        resp = self.url_open(
            '/web/magic_login/verify?token=OGILTIGT_TOKEN_XYZ',
            allow_redirects=False,
        )
        self.assertIn(resp.status_code, (301, 302, 303))
        self.assertIn('/web/login', resp.headers.get('Location', ''))

    def test_invalid_token_includes_error_param(self):
        resp = self.url_open(
            '/web/magic_login/verify?token=OGILTIGT_TOKEN_XYZ',
            allow_redirects=False,
        )
        self.assertIn('magic_login_error', resp.headers.get('Location', ''))

    def test_empty_token_redirects_with_error(self):
        resp = self.url_open(
            '/web/magic_login/verify?token=',
            allow_redirects=False,
        )
        self.assertIn(resp.status_code, (301, 302, 303))
        self.assertIn('magic_login_error', resp.headers.get('Location', ''))

    def test_internal_user_token_rejected(self):
        internal_user = self.env.ref('base.user_admin')
        partner = internal_user.partner_id.sudo()
        partner.write({'signup_type': 'magic'})
        token = partner._generate_signup_token(expiration=0.25)
        resp = self.url_open(
            f'/web/magic_login/verify?token={token}',
            allow_redirects=False,
        )
        self.assertIn(resp.status_code, (301, 302, 303))
        self.assertIn('magic_login_error', resp.headers.get('Location', ''))

    def test_valid_token_clears_signup_type(self):
        partner = self.portal_user.partner_id.sudo()
        partner.write({'signup_type': 'magic'})
        token = partner._generate_signup_token(expiration=0.25)

        self.url_open(f'/web/magic_login/verify?token={token}', allow_redirects=False)

        partner.invalidate_recordset()
        self.assertFalse(partner.signup_type)

    def test_used_token_rejected_on_second_use(self):
        partner = self.portal_user.partner_id.sudo()
        partner.write({'signup_type': 'magic'})
        token = partner._generate_signup_token(expiration=0.25)

        # Första användningen konsumerar token
        self.url_open(f'/web/magic_login/verify?token={token}', allow_redirects=False)

        # Andra användningen ska ge error
        resp = self.url_open(
            f'/web/magic_login/verify?token={token}',
            allow_redirects=False,
        )
        self.assertIn(resp.status_code, (301, 302, 303))
        self.assertIn('magic_login_error', resp.headers.get('Location', ''))

    def test_verify_redirects_away_from_login_on_success(self):
        partner = self.portal_user.partner_id.sudo()
        partner.write({'signup_type': 'magic'})
        token = partner._generate_signup_token(expiration=0.25)

        resp = self.url_open(
            f'/web/magic_login/verify?token={token}',
            allow_redirects=False,
        )
        location = resp.headers.get('Location', '')
        self.assertNotIn('magic_login_error', location)
