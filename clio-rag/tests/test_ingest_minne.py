"""
Tester för ingest_minne.py — felhantering per fil, utan Qdrant eller OpenAI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import ingest_minne


def test_ingest_files_all_ok():
    files = [Path("a.txt"), Path("b.txt")]
    with patch.object(ingest_minne, "ingest_file", return_value=3) as mock_ingest:
        total, failed = ingest_minne.ingest_files(files, "mem_test")
    assert total == 6
    assert failed == []
    assert mock_ingest.call_count == 2


def test_ingest_files_continues_after_failure(capsys):
    files = [Path("a.txt"), Path("trasig.docx"), Path("c.txt")]

    def fake_ingest(path, collection, force=False):
        if path.name == "trasig.docx":
            raise ValueError("is not a Word file")
        return 2

    with patch.object(ingest_minne, "ingest_file", side_effect=fake_ingest):
        total, failed = ingest_minne.ingest_files(files, "mem_test")
    assert total == 4
    assert failed == [Path("trasig.docx")]
    assert "FEL" in capsys.readouterr().out


def test_main_exits_2_when_files_fail(tmp_path):
    (tmp_path / "x.txt").write_text("text")
    argv = ["ingest_minne.py", "--source", str(tmp_path), "--collection", "mem_test"]
    with patch.object(sys, "argv", argv), \
         patch.object(ingest_minne, "ensure_collection"), \
         patch.object(ingest_minne, "ingest_file", side_effect=RuntimeError("boom")):
        with pytest.raises(SystemExit) as exc:
            ingest_minne.main()
    assert exc.value.code == 2


def test_main_returns_normally_when_all_ok(tmp_path):
    (tmp_path / "x.txt").write_text("text")
    argv = ["ingest_minne.py", "--source", str(tmp_path), "--collection", "mem_test"]
    with patch.object(sys, "argv", argv), \
         patch.object(ingest_minne, "ensure_collection"), \
         patch.object(ingest_minne, "ingest_file", return_value=1):
        ingest_minne.main()
