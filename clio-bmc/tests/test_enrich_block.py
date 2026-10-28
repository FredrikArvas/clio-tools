"""
test_enrich_block.py -- Enhetstester for enrich_block.py.
Claude API-anrop mockas med unittest.mock.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from session import BLOCK_NAMES, load_or_create, set_block_text
from enrich_block import enrich, enrich_all


def _make_session(tmp_path, bolag='TestBolag'):
    return load_or_create(bolag, 'as-is', '2026-01-01', tmp_path)


def _mock_claude_response(text: str):
    """Skapar ett mock-svar som liknar anthropic.messages.create()."""
    content = MagicMock()
    content.text = text
    msg = MagicMock()
    msg.content = [content]
    return msg


# ── Valideringsfel ────────────────────────────────────────────────────────────

class TestEnrichValidation:
    def test_unknown_block_raises_value_error(self, tmp_path):
        session = _make_session(tmp_path)
        with pytest.raises(ValueError, match='Okant block'):
            enrich(session, 'finns_ej_block')

    def test_empty_coach_text_returns_empty_string(self, tmp_path):
        session = _make_session(tmp_path)
        result = enrich(session, 'kundsegment')
        assert result == ''

    def test_empty_coach_text_does_not_call_claude(self, tmp_path):
        session = _make_session(tmp_path)
        with patch('enrich_block.anthropic.Anthropic') as mock_client:
            enrich(session, 'kundsegment')
            mock_client.assert_not_called()


# ── Lyckad berikaning ─────────────────────────────────────────────────────────

class TestEnrichSuccess:
    def test_returns_enriched_text(self, tmp_path):
        session = _make_session(tmp_path)
        set_block_text(session, 'kundsegment', 'B2B-foretag i Sverige')
        mock_resp = _mock_claude_response('Analys: Segmentet ar tillrackligt specifikt.')

        with patch('enrich_block.anthropic.Anthropic') as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            result = enrich(session, 'kundsegment', base_dir=tmp_path)

        assert result == 'Analys: Segmentet ar tillrackligt specifikt.'

    def test_sets_block_status_to_enriched(self, tmp_path):
        session = _make_session(tmp_path)
        set_block_text(session, 'kanaler', 'Direktforsaljning')
        mock_resp = _mock_claude_response('Kanalanalys.')

        with patch('enrich_block.anthropic.Anthropic') as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            enrich(session, 'kanaler', base_dir=tmp_path)

        assert session['blocks']['kanaler']['status'] == 'enriched'

    def test_stores_enriched_text_in_session(self, tmp_path):
        session = _make_session(tmp_path)
        set_block_text(session, 'intaktsstromar', 'Prenumerationsmodell')
        mock_resp = _mock_claude_response('Intaktsanalys: Prenumeration ar skalbart.')

        with patch('enrich_block.anthropic.Anthropic') as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            enrich(session, 'intaktsstromar', base_dir=tmp_path)

        assert 'Prenumeration' in session['blocks']['intaktsstromar']['enriched_text']

    def test_url_html_included_in_prompt(self, tmp_path):
        session = _make_session(tmp_path)
        set_block_text(session, 'vardeerbjudande', 'AI-plattform for HR')
        mock_resp = _mock_claude_response('VP-analys.')
        captured_prompt = []

        def capture_call(**kwargs):
            captured_prompt.append(kwargs['messages'][0]['content'])
            return mock_resp

        with patch('enrich_block.anthropic.Anthropic') as MockClient:
            MockClient.return_value.messages.create.side_effect = capture_call
            enrich(session, 'vardeerbjudande',
                   url_html='<html>Konkurrentens webbplats</html>',
                   base_dir=tmp_path)

        assert 'Konkurrentens webbplats' in captured_prompt[0]

    def test_saves_session_after_enrich(self, tmp_path):
        session = _make_session(tmp_path)
        set_block_text(session, 'kundsegment', 'Storforetag')
        mock_resp = _mock_claude_response('Analys.')

        with patch('enrich_block.anthropic.Anthropic') as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            enrich(session, 'kundsegment', base_dir=tmp_path)

        saved_files = list(tmp_path.glob('*.json'))
        assert len(saved_files) == 1


# ── enrich_all ────────────────────────────────────────────────────────────────

class TestEnrichAll:
    def test_enriches_only_blocks_with_coach_text(self, tmp_path):
        session = _make_session(tmp_path)
        set_block_text(session, 'kundsegment', 'Text A')
        set_block_text(session, 'kanaler', 'Text B')
        mock_resp = _mock_claude_response('Analys.')

        with patch('enrich_block.anthropic.Anthropic') as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            count = enrich_all(session, base_dir=tmp_path)

        assert count == 2

    def test_skips_empty_blocks(self, tmp_path):
        session = _make_session(tmp_path)
        mock_resp = _mock_claude_response('Analys.')

        with patch('enrich_block.anthropic.Anthropic') as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            count = enrich_all(session, base_dir=tmp_path)

        assert count == 0
        MockClient.return_value.messages.create.assert_not_called()

    def test_returns_count_of_enriched(self, tmp_path):
        session = _make_session(tmp_path)
        for name in BLOCK_NAMES[:3]:
            set_block_text(session, name, f'Text {name}')
        mock_resp = _mock_claude_response('Analys.')

        with patch('enrich_block.anthropic.Anthropic') as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            count = enrich_all(session, base_dir=tmp_path)

        assert count == 3
