import html
import logging
import re
import threading
import urllib.request
import urllib.error
import json

from odoo import api, models

logger = logging.getLogger('clio_discuss')


def _strip_html(raw: str) -> str:
    """Tar bort HTML-taggar och avkodar HTML-entiteter."""
    clean = re.sub(r'<[^>]+>', ' ', raw or '')
    return html.unescape(re.sub(r'\s+', ' ', clean).strip())


class ClioDiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def message_post(self, **kwargs):
        msg = super().message_post(**kwargs)

        clio_channel = self.env.ref(
            'clio_discuss.channel_clio', raise_if_not_found=False
        )
        if not clio_channel or self.id != clio_channel.id:
            return msg

        # Hoppa över svar från clio_post_reply (context-flagga) eller Clio Bot — förhindrar loop
        if self.env.context.get('clio_skip_hook'):
            return msg
        clio_bot = self.env.ref(
            'clio_discuss.partner_clio_bot', raise_if_not_found=False
        )
        if clio_bot and msg.author_id.id == clio_bot.id:
            return msg

        body_text = _strip_html(kwargs.get('body', ''))
        if not body_text:
            return msg

        sender_email = self.env.user.email or ''
        sender_name = self.env.user.name or ''
        channel_id = self.id

        config = self.env['ir.config_parameter'].sudo()
        agent_url = config.get_param(
            'clio_discuss.agent_url', 'http://localhost:8100/message'
        )
        shared_secret = config.get_param('clio_discuss.shared_secret', '')

        payload = json.dumps({
            'message':      body_text,
            'sender_email': sender_email,
            'sender_name':  sender_name,
            'channel_id':   channel_id,
            'secret':       shared_secret,
        }).encode()

        def _call_agent():
            try:
                req = urllib.request.Request(
                    agent_url,
                    data=payload,
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception as exc:
                logger.warning('clio_discuss: kunde inte nå agenten: %s', exc)

        t = threading.Thread(target=_call_agent, daemon=True)
        t.start()

        return msg

    @api.model
    def clio_post_reply(self, channel_id: int, body: str) -> bool:
        """
        Postar ett Clio-svar med sudo() och clio_skip_hook=True — hoppar över
        agent-hooken och behåller HTML-formatering.
        """
        channel = self.sudo().with_context(clio_skip_hook=True).browse(channel_id)
        channel.message_post(body=body, message_type='comment')
        return True
