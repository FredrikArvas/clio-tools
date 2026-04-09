"""
test_vision.py
Unit tests for clio-vision-batch.py

Tests:
    - find_images() discovers correct files
    - build_md() produces valid markdown
    - analyze_with_claude() with mocked API
    - analyze_with_ollama() with mocked API
    - DigiKam metadata reading (graceful when exiftool missing)
"""

import sys
import json
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "config"))

FIXTURES = Path(__file__).parent.parent / "fixtures"

import importlib.util
spec = importlib.util.spec_from_file_location(
    "clio_vision",
    Path(__file__).parent.parent.parent / "clio-vision" / "clio_vision.py"
)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    _MOD_LOADED = True
except Exception as e:
    _MOD_LOADED = False
    _MOD_ERROR = str(e)

SAMPLE_VISION_DATA = {
    "description": "A test image showing a simple pattern.",
    "tags": ["test", "pattern", "geometric"],
    "masterdata": {
        "location": None,
        "date": None,
        "people": [],
        "objects": ["rectangle", "text"],
        "text_in_image": "Clio Tools",
        "category": "illustration",
        "quality": "medium"
    }
}


@unittest.skipUnless(_MOD_LOADED, "clio-vision module could not be loaded")
class TestFindImages(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "photo.jpg").write_bytes(b"fake jpg")
        (self.tmp / "scan.png").write_bytes(b"fake png")
        (self.tmp / "photo_VISION.md").write_text("vision output")
        (self.tmp / "document.pdf").write_bytes(b"fake pdf")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_finds_image_formats(self):
        result = mod.find_images(self.tmp)
        names = [f.name for f in result]
        self.assertIn("photo.jpg", names)
        self.assertIn("scan.png", names)

    def test_excludes_vision_files(self):
        result = mod.find_images(self.tmp)
        names = [f.name for f in result]
        self.assertNotIn("photo_VISION.md", names)

    def test_excludes_non_images(self):
        result = mod.find_images(self.tmp)
        names = [f.name for f in result]
        self.assertNotIn("document.pdf", names)


@unittest.skipUnless(_MOD_LOADED, "clio-vision module could not be loaded")
class TestBuildMd(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.image = self.tmp / "test_photo.jpg"
        self.image.write_bytes(b"fake jpg")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_md_contains_description(self):
        digikam = {"people": [], "tags": [], "rating": None}
        result = mod.build_md(self.image, SAMPLE_VISION_DATA, digikam, "2026-03-29")
        self.assertIn("A test image showing", result)

    def test_md_contains_tags(self):
        digikam = {"people": [], "tags": [], "rating": None}
        result = mod.build_md(self.image, SAMPLE_VISION_DATA, digikam, "2026-03-29")
        self.assertIn("test", result)
        self.assertIn("pattern", result)

    def test_md_contains_filename(self):
        digikam = {"people": [], "tags": [], "rating": None}
        result = mod.build_md(self.image, SAMPLE_VISION_DATA, digikam, "2026-03-29")
        self.assertIn("test_photo", result)

    def test_md_contains_raw_json(self):
        digikam = {"people": [], "tags": [], "rating": None}
        result = mod.build_md(self.image, SAMPLE_VISION_DATA, digikam, "2026-03-29")
        self.assertIn("```json", result)

    def test_merges_digikam_people(self):
        digikam = {"people": ["Alice", "Bob"], "tags": ["family"], "rating": 4}
        result = mod.build_md(self.image, SAMPLE_VISION_DATA, digikam, "2026-03-29")
        self.assertIn("Alice", result)
        self.assertIn("Bob", result)

    def test_digikam_rating_shown(self):
        digikam = {"people": [], "tags": [], "rating": 4}
        result = mod.build_md(self.image, SAMPLE_VISION_DATA, digikam, "2026-03-29")
        self.assertIn("★", result)


@unittest.skipUnless(_MOD_LOADED, "clio-vision module could not be loaded")
class TestAnalyzeWithClaudeMocked(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.image = self.tmp / "test.jpg"
        self.image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_returns_parsed_data(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "content": [{"text": json.dumps(SAMPLE_VISION_DATA)}]
        }).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            ok, data, msg = mod.analyze_with_claude(self.image, "sk-ant-test")

        self.assertTrue(ok, f"analyze_with_claude failed: {msg}")
        self.assertEqual(data.get("description"), SAMPLE_VISION_DATA["description"])
        self.assertIn("test", data.get("tags", []))

    def test_handles_api_error_gracefully(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            ok, data, msg = mod.analyze_with_claude(self.image, "sk-ant-test")

        self.assertFalse(ok)
        self.assertIn("error", msg.lower())


@unittest.skipUnless(_MOD_LOADED, "clio-vision module could not be loaded")
class TestAnalyzeWithOllamaMocked(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.image = self.tmp / "test.jpg"
        self.image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_returns_parsed_data(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "response": json.dumps(SAMPLE_VISION_DATA)
        }).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            ok, data, msg = mod.analyze_with_ollama(self.image)

        self.assertTrue(ok, f"analyze_with_ollama failed: {msg}")

    def test_handles_ollama_not_running(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            ok, data, msg = mod.analyze_with_ollama(self.image)

        self.assertFalse(ok)


@unittest.skipUnless(_MOD_LOADED, "clio-vision module could not be loaded")
class TestDigikamMetadata(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.image = self.tmp / "test.jpg"
        self.image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_returns_empty_when_exiftool_missing(self):
        with patch.dict("sys.modules", {"exiftool": None}):
            result = mod.read_digikam_metadata(self.image)
        self.assertIn("people", result)
        self.assertIn("tags", result)
        self.assertEqual(result["people"], [])

    def test_returns_correct_structure(self):
        with patch("exiftool.ExifToolHelper") as mock_et:
            mock_et.return_value.__enter__ = lambda s: s
            mock_et.return_value.__exit__ = MagicMock(return_value=False)
            mock_et.return_value.get_metadata.return_value = [{}]
            result = mod.read_digikam_metadata(self.image)
        self.assertIsInstance(result["people"], list)
        self.assertIsInstance(result["tags"], list)


@unittest.skipUnless(_MOD_LOADED, "clio-vision module could not be loaded")
class TestAgentReady(unittest.TestCase):
    """Verifierar att clio-vision-batch kan köras utan interaktiva prompts.

    Design-princip: alla scripts i clio-tools ska vara agent-ready från start,
    dvs. alla interaktiva val ska kunna styras via CLI-flaggor.
    """

    def test_parse_args_engine_claude(self):
        args = mod.parse_args(["some/folder", "--engine", "claude"])
        self.assertEqual(args.engine, "claude")

    def test_parse_args_engine_haiku(self):
        args = mod.parse_args(["some/folder", "--engine", "haiku"])
        self.assertEqual(args.engine, "haiku")

    def test_parse_args_engine_ollama(self):
        args = mod.parse_args(["some/folder", "--engine", "ollama"])
        self.assertEqual(args.engine, "ollama")

    def test_parse_args_write_back_flag(self):
        args = mod.parse_args(["some/folder", "--write-back"])
        self.assertTrue(args.write_back)

    def test_parse_args_no_write_back_flag(self):
        args = mod.parse_args(["some/folder", "--no-write-back"])
        self.assertFalse(args.write_back)

    def test_parse_args_write_back_default_is_none(self):
        """Ingen flagga → None → interaktiv prompt visas."""
        args = mod.parse_args(["some/folder"])
        self.assertIsNone(args.write_back)

    def test_parse_args_recursive_flag(self):
        args = mod.parse_args(["some/folder", "--recursive"])
        self.assertTrue(args.recursive)

    def test_parse_args_recursive_short(self):
        args = mod.parse_args(["some/folder", "-r"])
        self.assertTrue(args.recursive)

    def test_parse_args_recursive_default_is_none(self):
        """Ingen flagga → None → interaktiv prompt visas."""
        args = mod.parse_args(["some/folder"])
        self.assertIsNone(args.recursive)

    def test_parse_args_yes_flag(self):
        args = mod.parse_args(["some/folder", "--yes"])
        self.assertTrue(args.yes)

    def test_parse_args_yes_short(self):
        args = mod.parse_args(["some/folder", "-y"])
        self.assertTrue(args.yes)

    def test_parse_args_yes_default_false(self):
        args = mod.parse_args(["some/folder"])
        self.assertFalse(args.yes)

    def test_parse_args_folder(self):
        args = mod.parse_args(["/some/path", "--engine", "ollama"])
        self.assertEqual(args.folder, "/some/path")

    def test_all_agent_flags_together(self):
        """Fullständigt agent-anrop: inga prompts behövs."""
        args = mod.parse_args([
            "/some/folder",
            "--engine", "ollama",
            "--write-back",
            "--recursive",
            "--yes",
        ])
        self.assertEqual(args.engine, "ollama")
        self.assertTrue(args.write_back)
        self.assertTrue(args.recursive)
        self.assertTrue(args.yes)

    def test_main_accepts_argv_parameter(self):
        """main() ska ta emot argv-lista (inte bara sys.argv) för testbarhet."""
        import inspect
        sig = inspect.signature(mod.main)
        self.assertIn("argv", sig.parameters)

    def test_parse_args_rejects_invalid_engine(self):
        """Okänd motor ger SystemExit (argparse-validering)."""
        with self.assertRaises(SystemExit):
            mod.parse_args(["folder", "--engine", "gpt4"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
