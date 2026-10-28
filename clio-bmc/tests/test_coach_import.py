"""
test_coach_import.py -- Enhetstester for coach_import.py.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from session import BLOCK_NAMES
from coach_import import import_coach_output


def _write_handoff(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / 'handoff.json'
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return p


# ── Import med 'blocks'-nyckel ────────────────────────────────────────────────

class TestImportWithBlocksKey:
    def test_imports_all_blocks(self, tmp_path):
        data = {
            'bolag': 'TestBolag',
            'version': 'as-is',
            'datum': '2026-01-01',
            'blocks': {name: f'Text for {name}' for name in BLOCK_NAMES},
        }
        f = _write_handoff(tmp_path, data)
        session = import_coach_output(str(f), 'fallback', 'as-is', '2026-01-01', tmp_path)
        for name in BLOCK_NAMES:
            assert session['blocks'][name]['coach_text'] == f'Text for {name}'

    def test_uses_bolag_from_file(self, tmp_path):
        data = {
            'bolag': 'FranFilen AB',
            'version': 'as-is',
            'datum': '2026-01-01',
            'blocks': {name: 'x' for name in BLOCK_NAMES},
        }
        f = _write_handoff(tmp_path, data)
        session = import_coach_output(str(f), 'Fallback', 'as-is', '2026-01-01', tmp_path)
        assert session['bolag'] == 'FranFilen AB'

    def test_saves_session_to_disk(self, tmp_path):
        sessions_dir = tmp_path / 'sessions'
        data = {
            'bolag': 'Sparat AB',
            'version': 'as-is',
            'datum': '2026-01-01',
            'blocks': {name: 'y' for name in BLOCK_NAMES},
        }
        f = _write_handoff(tmp_path, data)
        import_coach_output(str(f), 'Sparat AB', 'as-is', '2026-01-01', sessions_dir)
        saved_files = list(sessions_dir.glob('*.json'))
        assert len(saved_files) == 1


# ── Plant format (utan 'blocks'-nyckel) ──────────────────────────────────────

class TestImportFlatFormat:
    def test_imports_flat_handoff(self, tmp_path):
        data = {name: f'Flat text {name}' for name in BLOCK_NAMES}
        f = _write_handoff(tmp_path, data)
        session = import_coach_output(str(f), 'PlantBolag', 'as-is', '2026-01-01', tmp_path)
        assert session['blocks']['kundsegment']['coach_text'] == 'Flat text kundsegment'


# ── Partiellt handoff ─────────────────────────────────────────────────────────

class TestPartialHandoff:
    def test_partial_handoff_imports_what_exists(self, tmp_path):
        data = {'blocks': {'kundsegment': 'Bara ett block'}}
        f = _write_handoff(tmp_path, data)
        session = import_coach_output(str(f), 'Delvis', 'as-is', '2026-01-01', tmp_path)
        assert session['blocks']['kundsegment']['coach_text'] == 'Bara ett block'

    def test_missing_blocks_remain_empty(self, tmp_path):
        data = {'blocks': {'kundsegment': 'Bara ett block'}}
        f = _write_handoff(tmp_path, data)
        session = import_coach_output(str(f), 'Delvis', 'as-is', '2026-01-01', tmp_path)
        assert session['blocks']['kanaler']['coach_text'] == ''

    def test_empty_block_text_not_imported(self, tmp_path):
        data = {'blocks': {'kundsegment': '', 'kanaler': 'Kanaltext'}}
        f = _write_handoff(tmp_path, data)
        session = import_coach_output(str(f), 'T', 'as-is', '2026-01-01', tmp_path)
        assert session['blocks']['kundsegment']['coach_text'] == ''
        assert session['blocks']['kanaler']['coach_text'] == 'Kanaltext'


# ── Felfall ───────────────────────────────────────────────────────────────────

class TestImportErrors:
    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_coach_output(
                str(tmp_path / 'finns_ej.json'), 'T', 'as-is', '2026-01-01', tmp_path
            )

    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / 'bad.json'
        bad.write_text('detta ar inte json', encoding='utf-8')
        with pytest.raises(json.JSONDecodeError):
            import_coach_output(str(bad), 'T', 'as-is', '2026-01-01', tmp_path)
