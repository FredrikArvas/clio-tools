"""
test_push_notion.py -- Enhetstester for push_notion.py.
Notion-klienten mockas -- inga riktiga API-anrop gors.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from session import BLOCK_NAMES, load_or_create, set_block_enriched, set_block_text
from push_notion import build_page_children, push


def _make_session(tmp_path, bolag='TestBolag'):
    session = load_or_create(bolag, 'as-is', '2026-01-01', tmp_path)
    for name in BLOCK_NAMES:
        set_block_text(session, name, f'Coach-text for {name}')
        set_block_enriched(session, name, f'Clio-analys for {name}')
    return session


# ── build_page_children ───────────────────────────────────────────────────────

class TestBuildPageChildren:
    def test_returns_list(self, tmp_path):
        session = _make_session(tmp_path)
        children = build_page_children(session)
        assert isinstance(children, list)

    def test_contains_heading_for_each_block(self, tmp_path):
        session = _make_session(tmp_path)
        children = build_page_children(session)
        headings = [
            b for b in children
            if b.get('type') in ('heading_2', 'heading_3')
        ]
        assert len(headings) >= len(BLOCK_NAMES)

    def test_contains_metadata_paragraph(self, tmp_path):
        session = _make_session(tmp_path)
        children = build_page_children(session)
        first = children[0]
        assert first['type'] == 'paragraph'
        content = first['paragraph']['rich_text'][0]['text']['content']
        assert 'TestBolag' in content
        assert 'as-is' in content

    def test_empty_block_shows_placeholder(self, tmp_path):
        session = load_or_create('EmptyBolag', 'as-is', '2026-01-01', tmp_path)
        children = build_page_children(session)
        texts = [
            b['paragraph']['rich_text'][0]['text']['content']
            for b in children if b.get('type') == 'paragraph'
        ]
        assert any('(inte ifyllt)' in t for t in texts)

    def test_long_text_split_into_chunks(self, tmp_path):
        session = load_or_create('ChunkTest', 'as-is', '2026-01-01', tmp_path)
        long_text = 'X' * 5000
        set_block_text(session, 'kundsegment', long_text)
        set_block_enriched(session, 'kundsegment', long_text)
        children = build_page_children(session)
        paras = [b for b in children if b.get('type') == 'paragraph']
        for p in paras:
            content = p['paragraph']['rich_text'][0]['text']['content']
            assert len(content) <= 2000


# ── push -- dry-run ───────────────────────────────────────────────────────────

class TestPushDryRun:
    def test_dry_run_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv('NOTION_TOKEN', 'secret_test')
        session = _make_session(tmp_path)
        result = push(session, dry_run=True, base_dir=tmp_path)
        assert result is None

    def test_dry_run_does_not_call_notion_api(self, tmp_path, monkeypatch):
        monkeypatch.setenv('NOTION_TOKEN', 'secret_test')
        session = _make_session(tmp_path)
        with patch('push_notion.Client') as MockClient:
            push(session, dry_run=True, base_dir=tmp_path)
            MockClient.assert_not_called()


# ── push -- saknar token ──────────────────────────────────────────────────────

class TestPushMissingToken:
    def test_raises_environment_error_without_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv('NOTION_TOKEN', raising=False)
        session = _make_session(tmp_path)
        with pytest.raises(EnvironmentError, match='NOTION_TOKEN'):
            push(session, base_dir=tmp_path)


# ── push -- ny sida ───────────────────────────────────────────────────────────

class TestPushNewPage:
    def test_returns_page_id_on_success(self, tmp_path, monkeypatch):
        monkeypatch.setenv('NOTION_TOKEN', 'secret_test')
        session = _make_session(tmp_path)

        mock_client = MagicMock()
        mock_client.pages.create.return_value = {'id': 'abc-123-def'}
        mock_client.blocks.children.append.return_value = {}

        with patch('push_notion.Client', return_value=mock_client):
            result = push(session, base_dir=tmp_path)

        assert result == 'abc-123-def'

    def test_stores_page_id_in_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv('NOTION_TOKEN', 'secret_test')
        session = _make_session(tmp_path)

        mock_client = MagicMock()
        mock_client.pages.create.return_value = {'id': 'new-page-id'}
        mock_client.blocks.children.append.return_value = {}

        with patch('push_notion.Client', return_value=mock_client):
            push(session, base_dir=tmp_path)

        assert session['notion_page_id'] == 'new-page-id'

    def test_marks_enriched_blocks_as_pushed(self, tmp_path, monkeypatch):
        monkeypatch.setenv('NOTION_TOKEN', 'secret_test')
        session = _make_session(tmp_path)

        mock_client = MagicMock()
        mock_client.pages.create.return_value = {'id': 'page-xyz'}
        mock_client.blocks.children.append.return_value = {}

        with patch('push_notion.Client', return_value=mock_client):
            push(session, base_dir=tmp_path)

        for name in BLOCK_NAMES:
            assert session['blocks'][name]['status'] == 'pushed'


# ── push -- uppdatera befintlig sida ─────────────────────────────────────────

class TestPushUpdateExisting:
    def test_updates_existing_page_if_id_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv('NOTION_TOKEN', 'secret_test')
        session = _make_session(tmp_path)
        session['notion_page_id'] = 'existing-page-id'

        mock_client = MagicMock()
        mock_client.blocks.children.list.return_value = {'results': []}
        mock_client.blocks.children.append.return_value = {}

        with patch('push_notion.Client', return_value=mock_client):
            result = push(session, base_dir=tmp_path)

        assert result == 'existing-page-id'
        mock_client.pages.create.assert_not_called()
