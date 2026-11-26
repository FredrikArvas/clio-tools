import logging
import werkzeug.urls

from odoo import http, _
from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.web.controllers.home import ensure_db
from odoo.http import request

_logger = logging.getLogger(__name__)

MAGIC_LINK_EXPIRY_HOURS = 0.25  # 15 minutes


class MagicLoginController(AuthSignupHome):

    @http.route()
    def web_login(self, *args, **kw):
        ensure_db()

        # Intercept magic link POST before super handles it
        if request.httprequest.method == 'POST' and request.params.get('type') == 'magic_link':
            return self._magic_link_send(**kw)

        # Let parent handle password POST and all redirect/session logic
        response = super().web_login(*args, **kw)

        # For GET requests when not yet logged in: replace with our signup-first template
        qcontext = getattr(response, 'qcontext', None)
        if qcontext is not None and request.httprequest.method == 'GET' and not request.session.uid:
            qcontext['magic_link_sent'] = bool(request.params.get('magic_link_sent'))
            if request.params.get('magic_login_error'):
                qcontext['error'] = request.params.get('magic_login_error')
            new_response = request.render('clio_magic_login.login', qcontext)
            new_response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            new_response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
            return new_response

        return response

    @http.route('/web/magic_login/verify', type='http', auth='none', methods=['GET'], csrf=False)
    def magic_login_verify(self, token='', redirect='', **kw):
        ensure_db()

        try:
            partner = request.env['res.partner'].sudo()._get_partner_from_token(token)
        except Exception:
            partner = None

        if not partner:
            return self._magic_login_redirect_error(_("Inloggningslänken är ogiltig eller har redan använts."))

        if not partner.user_ids:
            return self._magic_login_redirect_error(_("Inget konto är kopplat till den här länken."))

        user = partner.user_ids[0]

        if user._is_internal():
            return self._magic_login_redirect_error(_("Interna användare loggar in med lösenord."))

        if not user.active:
            return self._magic_login_redirect_error(_("Kontot är inaktiverat."))

        # Invalidate token by clearing signup_type (prevents reuse within expiry window)
        partner.sudo().write({'signup_type': False})

        # Log in the user directly via session.finalize pattern
        request.session['pre_login'] = user.login
        request.session['pre_uid'] = user.id
        request.session.finalize(request.env)
        request.update_env(user=user)

        _logger.info("Magic link login: user %s (%s) logged in from %s",
                     user.login, user.id, request.httprequest.remote_addr)

        return request.redirect(redirect or '/odoo')

    def _magic_link_send(self, login='', redirect='', **kw):
        qcontext = self.get_auth_signup_qcontext()
        qcontext.update(self.get_auth_signup_config())

        login = login.strip().lower()
        if not login:
            qcontext['error'] = _("Ange din e-postadress.")
            new_response = request.render('clio_magic_login.login', qcontext)
            new_response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            return new_response

        # Look up portal user — don't reveal whether account exists
        User = request.env['res.users'].sudo()
        user = User.search([
            ('login', '=', login),
            ('active', '=', True),
            ('share', '=', True),  # portal/public users only
        ], limit=1)

        if user:
            try:
                self._send_magic_link_email(user, redirect)
            except Exception:
                _logger.exception("Failed to send magic link to %s", login)

        # Always show "check your email" — don't leak account existence
        qcontext['magic_link_sent'] = True
        new_response = request.render('clio_magic_login.login', qcontext)
        new_response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        new_response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        return new_response

    def _send_magic_link_email(self, user, redirect=''):
        partner = user.partner_id.sudo()
        partner.write({'signup_type': 'magic'})
        token = partner._generate_signup_token(expiration=MAGIC_LINK_EXPIRY_HOURS)

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        verify_url = '%s/web/magic_login/verify?token=%s' % (base_url, token)
        if redirect:
            verify_url += '&redirect=%s' % werkzeug.urls.url_quote(redirect)

        template = request.env.ref(
            'clio_magic_login.email_template_magic_link', raise_if_not_found=False
        )
        if template:
            template.sudo().with_context(verify_url=verify_url).send_mail(
                user.id, force_send=True
            )

    def _magic_login_redirect_error(self, message):
        # Redirect to login page with error as URL param — avoids website-context issues
        url = '/web/login?%s' % werkzeug.urls.url_encode({'magic_login_error': message})
        return request.redirect(url)
