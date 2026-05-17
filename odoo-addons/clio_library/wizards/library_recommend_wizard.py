import json
import os
import urllib.request
import urllib.error

from odoo import models, fields
from odoo.exceptions import UserError

ANTHROPIC_API = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_MODEL = 'claude-sonnet-4-6'
MIN_RATING = 4
MAX_RATING = 2


class LibraryRecommendWizard(models.TransientModel):
    _name = 'library.recommend.wizard'
    _description = 'Bokrekommendation'

    member_ids = fields.Many2many('res.users', string='Deltagare')
    blacklist_ids = fields.Many2many(
        'library.book', string='Uteslut böcker',
        relation='library_recommend_blacklist_rel',
    )
    recommendation = fields.Text(string='Rekommendation', readonly=True)

    def action_recommend(self):
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise UserError('ANTHROPIC_API_KEY saknas i serverns miljövariabler.')

        members = self.member_ids
        if not members:
            raise UserError('Välj minst en deltagare.')

        # Hämta betyg för valda användare
        all_ratings = self.env['library.rating'].search([
            ('user_id', 'in', members.ids)
        ])
        books = {b.id: b for b in self.env['library.book'].search([])}

        ratings_by_user = {m.id: {} for m in members}
        for r in all_ratings:
            ratings_by_user[r.user_id.id][r.book_id.id] = r.rating

        blacklist_ids = set(self.blacklist_ids.ids)

        liked = {m.id: [] for m in members}
        disliked = {m.id: [] for m in members}
        for m in members:
            for book_id, rating in ratings_by_user[m.id].items():
                if rating >= MIN_RATING:
                    liked[m.id].append(book_id)
                elif rating <= MAX_RATING:
                    disliked[m.id].append(book_id)

        # Böcker som alla har läst
        all_read = set(ratings_by_user[members[0].id].keys())
        for m in members[1:]:
            all_read &= set(ratings_by_user[m.id].keys())

        all_like = [bid for bid in all_read if all(bid in liked[m.id] for m in members)]
        mixed = [bid for bid in all_read if bid not in all_like]

        def book_str(bid):
            b = books.get(bid)
            if not b:
                return f'BOK-{bid}'
            return f'{b.name} av {b.author}' if b.author else b.name

        member_names = ', '.join(m.name for m in members)
        all_like_str = '\n'.join(f'- {book_str(bid)}' for bid in all_like[:15]) or '(inga gemensamma favoriter)'
        mixed_str = '\n'.join(f'- {book_str(bid)}' for bid in mixed[:10]) or '(inga)'

        taste_parts = []
        for m in members:
            like_titles = [book_str(bid) for bid in liked[m.id][:10]]
            dislike_titles = [book_str(bid) for bid in disliked[m.id][:5]]
            part = f'{m.name} gillar: {", ".join(like_titles) or "(inget registrerat)"}'
            if dislike_titles:
                part += f'\n{m.name} ogillar: {", ".join(dislike_titles)}'
            taste_parts.append(part)

        blacklist_str = '\n'.join(f'- {book_str(bid)}' for bid in blacklist_ids) or '(inga)'

        prompt = (
            f'Du är Clio, en bokklubbsrådgivare med djup litterär smak.\n\n'
            f'Du ska rekommendera nästa bok för en bokklubb med {len(members)} '
            f'deltagare: {member_names}.\n\n'
            f'SMAKPROFILER:\n{chr(10).join(taste_parts)}\n\n'
            f'BÖCKER ALLA GILLAR (betyg ≥ {MIN_RATING}):\n{all_like_str}\n\n'
            f'BÖCKER MED DELADE MENINGAR:\n{mixed_str}\n\n'
            f'UTESLUT DESSA BÖCKER:\n{blacklist_str}\n\n'
            f'Baserat på smakprofilerna, rekommendera EN specifik bok som gruppen '
            f'troligen kommer att gilla. Motivera varför just den boken passar alla '
            f'deltagare. Ange titel, författare och en kort beskrivning. Svara på svenska.'
        )

        payload = json.dumps({
            'model': ANTHROPIC_MODEL,
            'max_tokens': 1024,
            'messages': [{'role': 'user', 'content': prompt}],
        }).encode()

        req = urllib.request.Request(
            ANTHROPIC_API,
            data=payload,
            method='POST',
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            self.recommendation = result['content'][0]['text']
        except urllib.error.HTTPError as e:
            raise UserError(f'Anthropic API-fel {e.code}: {e.read().decode()[:300]}')
        except Exception as e:
            raise UserError(f'Fel vid API-anrop: {e}')

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
