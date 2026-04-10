"""
test_clio.py
Unit tests for clio.py navigation logic.

Tests:
    - BackToMenu exception
    - _input()
    - select_folder()
    - _gedcom_has_asterisk()
    - _pick_person()
    - run_research() — BackToMenu handling + cmd building
    - run_tool()     — BackToMenu handling
"""

import sys
import textwrap
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import clio

# Silence all print() output during tests
_NOP = patch("builtins.print")


# ── BackToMenu + _input ───────────────────────────────────────────────────────

class TestInput(unittest.TestCase):

    def test_returns_value(self):
        with patch("builtins.input", return_value="hello"):
            self.assertEqual(clio._input("p"), "hello")

    def test_returns_empty_string(self):
        with patch("builtins.input", return_value=""):
            self.assertEqual(clio._input("p"), "")

    def test_raises_on_zero(self):
        with patch("builtins.input", return_value="0"):
            with self.assertRaises(clio.BackToMenu):
                clio._input("p")

    def test_raises_on_zero_with_whitespace(self):
        with patch("builtins.input", return_value="  0  "):
            with self.assertRaises(clio.BackToMenu):
                clio._input("p")

    def test_does_not_raise_on_double_zero(self):
        with patch("builtins.input", return_value="00"):
            self.assertEqual(clio._input("p"), "00")

    def test_does_not_raise_on_nonzero_values(self):
        for val in ["1", "j", "n", "text", "0x"]:
            with patch("builtins.input", return_value=val):
                self.assertEqual(clio._input("p"), val)  # no exception


# ── select_folder ─────────────────────────────────────────────────────────────

class TestSelectFolder(unittest.TestCase):

    def setUp(self):
        _NOP.start()

    def tearDown(self):
        _NOP.stop()

    def test_returns_last_on_empty_answer(self):
        state = {"last_folder": {"t": "/last"}}
        with patch("builtins.input", return_value=""):
            self.assertEqual(clio.select_folder("t", state), "/last")

    def test_returns_last_on_j(self):
        state = {"last_folder": {"t": "/last"}}
        with patch("builtins.input", return_value="J"):
            self.assertEqual(clio.select_folder("t", state), "/last")

    def test_backtomenu_at_same_folder_prompt(self):
        state = {"last_folder": {"t": "/last"}}
        with patch("builtins.input", return_value="0"):
            with self.assertRaises(clio.BackToMenu):
                clio.select_folder("t", state)

    def test_returns_manual_path_when_no_last(self):
        with patch("builtins.input", return_value="/new/path"):
            self.assertEqual(clio.select_folder("t", {}), "/new/path")

    def test_returns_none_on_empty_when_no_last(self):
        with patch("builtins.input", return_value=""):
            self.assertIsNone(clio.select_folder("t", {}))

    def test_backtomenu_at_folder_entry(self):
        with patch("builtins.input", return_value="0"):
            with self.assertRaises(clio.BackToMenu):
                clio.select_folder("t", {})

    def test_returns_recent_folder_by_number(self):
        # recent reversed and filtered: ["/c", "/b"] → "1" = "/c"
        state = {"last_folder": {"t": "/a"}, "recent_folders": ["/b", "/c"]}
        with patch("builtins.input", side_effect=["n", "1"]):
            self.assertEqual(clio.select_folder("t", state), "/c")

    def test_backtomenu_at_choice_prompt(self):
        state = {"last_folder": {"t": "/a"}, "recent_folders": ["/b", "/c"]}
        with patch("builtins.input", side_effect=["n", "0"]):
            with self.assertRaises(clio.BackToMenu):
                clio.select_folder("t", state)


# ── _gedcom_has_asterisk ──────────────────────────────────────────────────────

class TestGedcomHasAsterisk(unittest.TestCase):

    def _tmp_ged(self, content):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".ged", delete=False, encoding="utf-8"
        )
        f.write(textwrap.dedent(content))
        f.close()
        return f.name

    def test_true_when_asterisk_in_name(self):
        path = self._tmp_ged("""\
            0 @I1@ INDI
            1 NAME Johan *Svensson*
            1 BIRT
        """)
        try:
            self.assertTrue(clio._gedcom_has_asterisk(path, "@I1@"))
        finally:
            Path(path).unlink()

    def test_false_when_no_asterisk(self):
        path = self._tmp_ged("""\
            0 @I1@ INDI
            1 NAME Johan Svensson
        """)
        try:
            self.assertFalse(clio._gedcom_has_asterisk(path, "@I1@"))
        finally:
            Path(path).unlink()

    def test_false_for_wrong_id(self):
        path = self._tmp_ged("""\
            0 @I1@ INDI
            1 NAME Johan *Svensson*
        """)
        try:
            self.assertFalse(clio._gedcom_has_asterisk(path, "@I99@"))
        finally:
            Path(path).unlink()

    def test_stops_at_next_record(self):
        # Asterisk belongs to @I2@, not @I1@
        path = self._tmp_ged("""\
            0 @I1@ INDI
            1 NAME Anna Larsson
            0 @I2@ INDI
            1 NAME Johan *Svensson*
        """)
        try:
            self.assertFalse(clio._gedcom_has_asterisk(path, "@I1@"))
            self.assertTrue(clio._gedcom_has_asterisk(path, "@I2@"))
        finally:
            Path(path).unlink()

    def test_false_on_missing_file(self):
        self.assertFalse(clio._gedcom_has_asterisk("/no/such/file.ged", "@I1@"))


# ── _pick_person ──────────────────────────────────────────────────────────────

class TestPickPerson(unittest.TestCase):

    def setUp(self):
        _NOP.start()

    def tearDown(self):
        _NOP.stop()

    def test_returns_id_on_direct_entry(self):
        with patch("builtins.input", side_effect=["", "@I42@"]):
            self.assertEqual(clio._pick_person("/f.ged"), "@I42@")

    def test_wraps_id_without_at_signs(self):
        with patch("builtins.input", side_effect=["", "I42"]):
            self.assertEqual(clio._pick_person("/f.ged"), "@I42@")

    def test_returns_none_on_empty_query_and_empty_id(self):
        with patch("builtins.input", side_effect=["", ""]):
            self.assertIsNone(clio._pick_person("/f.ged"))

    def test_backtomenu_at_query_prompt(self):
        with patch("builtins.input", return_value="0"):
            with self.assertRaises(clio.BackToMenu):
                clio._pick_person("/f.ged")

    def test_backtomenu_at_direct_id_prompt(self):
        with patch("builtins.input", side_effect=["", "0"]):
            with self.assertRaises(clio.BackToMenu):
                clio._pick_person("/f.ged")

    def test_returns_single_match_directly(self):
        matches = [{"id": "@I5@", "name": "Anna Svensson"}]
        with patch("clio._search_gedcom_persons", return_value=matches):
            with patch("builtins.input", return_value="Anna"):
                self.assertEqual(clio._pick_person("/f.ged"), "@I5@")

    def test_returns_selected_from_multiple(self):
        matches = [
            {"id": "@I1@", "name": "Anna Svensson"},
            {"id": "@I2@", "name": "Anna Larsson"},
        ]
        with patch("clio._search_gedcom_persons", return_value=matches):
            with patch("builtins.input", side_effect=["Anna", "2"]):
                self.assertEqual(clio._pick_person("/f.ged"), "@I2@")

    def test_backtomenu_at_match_selection(self):
        matches = [
            {"id": "@I1@", "name": "Anna Svensson"},
            {"id": "@I2@", "name": "Anna Larsson"},
        ]
        with patch("clio._search_gedcom_persons", return_value=matches):
            with patch("builtins.input", side_effect=["Anna", "0"]):
                with self.assertRaises(clio.BackToMenu):
                    clio._pick_person("/f.ged")

    def test_empty_selection_loops_back_to_search(self):
        # First search: no match. Second search: one match.
        no_match = []
        one_match = [{"id": "@I7@", "name": "Erik Persson"}]
        results = iter([no_match, one_match])
        with patch("clio._search_gedcom_persons", side_effect=results):
            with patch("builtins.input", side_effect=["typo", "erik"]):
                self.assertEqual(clio._pick_person("/f.ged"), "@I7@")


# ── run_research: BackToMenu handling ────────────────────────────────────────

class TestRunResearchBackToMenu(unittest.TestCase):

    def setUp(self):
        _NOP.start()
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
        tmp.close()
        self.tool = {"name": "clio-research", "script": Path(tmp.name)}
        self._tmp = tmp.name

    def tearDown(self):
        _NOP.stop()
        Path(self._tmp).unlink(missing_ok=True)

    def test_backtomenu_from_select_gedcom(self):
        with patch("clio.select_gedcom", side_effect=clio.BackToMenu):
            clio.run_research(self.tool, {})  # must not raise

    def test_backtomenu_from_mode_prompt(self):
        with patch("clio.select_gedcom", return_value=self._tmp):
            with patch("builtins.input", return_value="0"):
                clio.run_research(self.tool, {})  # must not raise

    def test_backtomenu_from_syfte_in_mode1(self):
        with patch("clio.select_gedcom", return_value=self._tmp):
            with patch("clio._pick_person", return_value="@I1@"):
                with patch("clio._gedcom_has_asterisk", return_value=False):
                    with patch("builtins.input", side_effect=["1", "0"]):
                        clio.run_research(self.tool, {})  # must not raise

    def test_backtomenu_from_surname_in_mode2(self):
        with patch("clio.select_gedcom", return_value=self._tmp):
            with patch("builtins.input", side_effect=["2", "0"]):
                clio.run_research(self.tool, {})  # must not raise

    def test_backtomenu_from_review_id_in_mode4(self):
        with patch("clio.select_gedcom", return_value=self._tmp):
            with patch("builtins.input", side_effect=["4", "0"]):
                clio.run_research(self.tool, {})  # must not raise


# ── run_research: cmd building ────────────────────────────────────────────────

class TestRunResearchCmd(unittest.TestCase):
    """Verifies that the correct CLI flags are built for each mode.

    Mode 1 design (current):
      - possibly_living=False: optional syfte, then dry-run
      - possibly_living=True:  required syfte (loop until non-empty), then dry-run,
                               always adds --levande ja
    Mode 4 design (current):
      - runs --status (godkännande hanteras inuti research.py)
    """

    def setUp(self):
        _NOP.start()
        tmp_script = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
        tmp_script.close()
        tmp_ged = tempfile.NamedTemporaryFile(suffix=".ged", delete=False)
        tmp_ged.close()
        self.tool = {"name": "clio-research", "script": Path(tmp_script.name)}
        self._script = tmp_script.name
        self._ged = tmp_ged.name

    def tearDown(self):
        _NOP.stop()
        Path(self._script).unlink(missing_ok=True)
        Path(self._ged).unlink(missing_ok=True)

    def _run(self, input_values, pick_person="@I1@", has_asterisk=False):
        """Run run_research with mocked deps; returns the last subprocess cmd list."""
        mock_result = MagicMock()
        mock_result.stdout = ""  # no "Inga väntande" → mode 4 continues past status check
        with patch("clio.select_gedcom", return_value=self._ged):
            with patch("clio._pick_person", return_value=pick_person):
                with patch("clio._gedcom_has_asterisk", return_value=has_asterisk):
                    with patch("clio.save_state"):
                        with patch("subprocess.run", return_value=mock_result) as mock_run:
                            with patch("builtins.input", side_effect=input_values):
                                clio.run_research(self.tool, {})
                            if mock_run.called:
                                return mock_run.call_args[0][0]
                            return None

    def test_mode3_status_flag(self):
        # mode="3", then menu_continue=""
        cmd = self._run(["3", ""])
        self.assertIn("--status", cmd)

    def test_mode1_includes_gedcom_id_and_file(self):
        # mode="1", optional syfte="", dry="", menu_continue=""
        cmd = self._run(["1", "", "", ""])
        self.assertIn("--gedcom-id", cmd)
        self.assertIn("@I1@", cmd)
        self.assertIn("--gedcom-file", cmd)

    def test_mode1_default_is_dry_run(self):
        cmd = self._run(["1", "", "", ""])
        self.assertIn("--dry-run", cmd)

    def test_mode1_no_dry_run_on_n(self):
        cmd = self._run(["1", "", "n", ""])
        self.assertNotIn("--dry-run", cmd)

    def test_mode1_syfte_included(self):
        cmd = self._run(["1", "guldboda-75", "n", ""])
        self.assertIn("--syfte", cmd)
        self.assertIn("guldboda-75", cmd)

    def test_mode1_no_syfte_when_empty(self):
        cmd = self._run(["1", "", "n", ""])
        self.assertNotIn("--syfte", cmd)

    def test_mode2_batch_and_gedcom_file(self):
        # mode="2", surname="", syfte="", dry="", menu_continue=""
        cmd = self._run(["2", "", "", "", ""])
        self.assertIn("--batch", cmd)
        self.assertIn("--gedcom-file", cmd)

    def test_mode2_surname_filter(self):
        cmd = self._run(["2", "Svensson", "", "n", ""])
        self.assertIn("--filter-surname", cmd)
        self.assertIn("Svensson", cmd)

    def test_mode2_no_surname_omits_filter(self):
        cmd = self._run(["2", "", "", "n", ""])
        self.assertNotIn("--filter-surname", cmd)

    def test_mode4_runs_status(self):
        # mode="4" → --status (godkännande sker direkt i research.py)
        cmd = self._run(["4", ""])
        self.assertIn("--status", cmd)

    def test_mode1_levande_ja_when_asterisk(self):
        # possibly_living=True → required syfte (must be non-empty), always --levande ja
        # inputs: mode, syfte (non-empty required), dry, menu_continue
        cmd = self._run(["1", "guldboda-75", "n", ""], has_asterisk=True)
        self.assertIn("--levande", cmd)
        self.assertIn("ja", cmd)

    def test_mode1_levande_syfte_required_loops_until_non_empty(self):
        # First syfte="" → loop repeats; second syfte="familjeminnet" → breaks
        cmd = self._run(["1", "", "familjeminnet", "n", ""], has_asterisk=True)
        self.assertIn("--syfte", cmd)
        self.assertIn("familjeminnet", cmd)

    def test_mode1_no_levande_when_no_asterisk(self):
        cmd = self._run(["1", "", "n", ""], has_asterisk=False)
        self.assertNotIn("--levande", cmd)


# ── run_tool: BackToMenu handling ─────────────────────────────────────────────

class TestRunTool(unittest.TestCase):

    def setUp(self):
        _NOP.start()
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False)
        tmp.close()
        self._script = tmp.name

    def tearDown(self):
        _NOP.stop()
        Path(self._script).unlink(missing_ok=True)

    def test_backtomenu_from_select_folder_prevents_subprocess(self):
        tool = {
            "name": "clio-docs",
            "script": Path(self._script),
            "needs_folder": True,
        }
        with patch("clio.select_folder", side_effect=clio.BackToMenu):
            with patch("subprocess.run") as mock_run:
                clio.run_tool(tool, {})
                mock_run.assert_not_called()

    def test_no_folder_tool_never_calls_select_folder(self):
        tool = {
            "name": "clio-emailfetch",
            "script": Path(self._script),
            "needs_folder": False,
        }
        with patch("clio.select_folder") as mock_sf:
            with patch("subprocess.run"):
                with patch("clio.save_state"):
                    with patch("clio.register_run"):
                        with patch("builtins.input", return_value=""):
                            clio.run_tool(tool, {})
            mock_sf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
