"""
test_session.py -- Enhetstester for session.py.
Alla disk-operationer anvander tmp_path fran pytest.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from session import (
    BLOCK_NAMES,
    get_block,
    load_or_create,
    save,
    session_path,
    set_block_enriched,
    set_block_pushed,
    set_block_text,
    status_summary,
)


# ── session_path ──────────────────────────────────────────────────────────────

class TestSessionPath:
    def test_slugifies_bolag(self, tmp_path):
        p = session_path('Acme AB', 'as-is', '2026-01-01', tmp_path)
        assert 'acme-ab' in p.name

    def test_includes_version(self, tmp_path):
        p = session_path('Test', 'to-be', '2026-01-01', tmp_path)
        assert 'to-be' in p.name

    def test_includes_datum(self, tmp_path):
        p = session_path('Test', 'as-is', '2026-05-06', tmp_path)
        assert '2026-05-06' in p.name

    def test_is_json_file(self, tmp_path):
        p = session_path('Test', 'as-is', '2026-01-01', tmp_path)
        assert p.suffix == '.json'

    def test_swedish_chars_slugified(self, tmp_path):
        p = session_path('Arvas International AB', 'as-is', '2026-01-01', tmp_path)
        assert 'arvas-international-ab' in p.name


# ── load_or_create ────────────────────────────────────────────────────────────

class TestLoadOrCreate:
    def test_creates_new_session_with_all_blocks(self, tmp_path):
        session = load_or_create('TestBolag', 'as-is', '2026-01-01', tmp_path)
        assert set(session['blocks'].keys()) == set(BLOCK_NAMES)

    def test_new_session_blocks_are_pending(self, tmp_path):
        session = load_or_create('TestBolag', 'as-is', '2026-01-01', tmp_path)
        for block in session['blocks'].values():
            assert block['status'] == 'pending'

    def test_new_session_stores_metadata(self, tmp_path):
        session = load_or_create('TestBolag', 'as-is', '2026-01-01', tmp_path)
        assert session['bolag'] == 'TestBolag'
        assert session['version'] == 'as-is'
        assert session['datum'] == '2026-01-01'

    def test_new_session_notion_page_id_is_none(self, tmp_path):
        session = load_or_create('TestBolag', 'as-is', '2026-01-01', tmp_path)
        assert session['notion_page_id'] is None

    def test_reloads_existing_session(self, tmp_path):
        session = load_or_create('TestBolag', 'as-is', '2026-01-01', tmp_path)
        set_block_text(session, 'kundsegment', 'Konsulter pa storforetag')
        save(session, tmp_path)

        reloaded = load_or_create('TestBolag', 'as-is', '2026-01-01', tmp_path)
        assert reloaded['blocks']['kundsegment']['coach_text'] == 'Konsulter pa storforetag'


# ── set_block_text ────────────────────────────────────────────────────────────

class TestSetBlockText:
    def test_sets_coach_text(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_text(session, 'kundsegment', 'B2B-foretag med 50-200 anstallda')
        assert session['blocks']['kundsegment']['coach_text'] == 'B2B-foretag med 50-200 anstallda'

    def test_does_not_change_status(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_text(session, 'kanaler', 'Direktforsaljning')
        assert session['blocks']['kanaler']['status'] == 'pending'


# ── set_block_enriched ────────────────────────────────────────────────────────

class TestSetBlockEnriched:
    def test_sets_enriched_text(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_enriched(session, 'kundsegment', 'Analys av segmentet...')
        assert session['blocks']['kundsegment']['enriched_text'] == 'Analys av segmentet...'

    def test_changes_status_to_enriched(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_enriched(session, 'kundsegment', 'Analys...')
        assert session['blocks']['kundsegment']['status'] == 'enriched'

    def test_stores_urls(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_enriched(session, 'kundsegment', 'Analys...', ['https://example.com'])
        assert 'https://example.com' in session['blocks']['kundsegment']['urls_fetched']

    def test_urls_none_leaves_empty_list(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_enriched(session, 'kundsegment', 'Analys...', None)
        assert session['blocks']['kundsegment']['urls_fetched'] == []


# ── set_block_pushed ──────────────────────────────────────────────────────────

class TestSetBlockPushed:
    def test_sets_status_pushed(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_pushed(session, 'kanaler')
        assert session['blocks']['kanaler']['status'] == 'pushed'


# ── get_block ─────────────────────────────────────────────────────────────────

class TestGetBlock:
    def test_returns_block_dict(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        block = get_block(session, 'intaktsstromar')
        assert 'coach_text' in block
        assert 'enriched_text' in block
        assert 'status' in block


# ── status_summary ────────────────────────────────────────────────────────────

class TestStatusSummary:
    def test_all_pending_initially(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        counts = status_summary(session)
        assert counts['pending'] == len(BLOCK_NAMES)
        assert counts['enriched'] == 0
        assert counts['pushed'] == 0

    def test_counts_update_after_enriched(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_enriched(session, 'kundsegment', 'Analys...')
        set_block_enriched(session, 'kanaler', 'Kanalanalys...')
        counts = status_summary(session)
        assert counts['enriched'] == 2
        assert counts['pending'] == len(BLOCK_NAMES) - 2

    def test_counts_all_statuses(self, tmp_path):
        session = load_or_create('T', 'as-is', '2026-01-01', tmp_path)
        set_block_enriched(session, 'kundsegment', 'x')
        set_block_pushed(session, 'kanaler')
        counts = status_summary(session)
        assert counts['enriched'] == 1
        assert counts['pushed'] == 1
        assert counts['pending'] == len(BLOCK_NAMES) - 2


# ── save ──────────────────────────────────────────────────────────────────────

class TestSave:
    def test_creates_file(self, tmp_path):
        session = load_or_create('SaveTest', 'as-is', '2026-01-01', tmp_path)
        path = save(session, tmp_path)
        assert path.exists()

    def test_file_is_valid_json(self, tmp_path):
        session = load_or_create('SaveTest', 'as-is', '2026-01-01', tmp_path)
        path = save(session, tmp_path)
        data = json.loads(path.read_text(encoding='utf-8'))
        assert data['bolag'] == 'SaveTest'

    def test_roundtrip_preserves_content(self, tmp_path):
        session = load_or_create('SaveTest', 'as-is', '2026-01-01', tmp_path)
        set_block_text(session, 'kostnadsstruktur', 'Personal och lokaler')
        save(session, tmp_path)
        reloaded = json.loads(
            session_path('SaveTest', 'as-is', '2026-01-01', tmp_path)
            .read_text(encoding='utf-8')
        )
        assert reloaded['blocks']['kostnadsstruktur']['coach_text'] == 'Personal och lokaler'
