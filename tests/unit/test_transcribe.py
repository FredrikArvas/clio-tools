"""
test_transcribe.py
Unit tests for clio-transcribe-batch.py

Tests:
    - find_audio_files() discovers correct files
    - _format_time() formats correctly
    - transcribe() with mocked WhisperModel
    - temp file workaround for non-ASCII paths
"""

import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "config"))

FIXTURES = Path(__file__).parent.parent / "fixtures"

import importlib.util
spec = importlib.util.spec_from_file_location(
    "clio_transcribe",
    Path(__file__).parent.parent.parent / "clio-transcribe" / "clio-transcribe-batch.py"
)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    _MOD_LOADED = True
except Exception as e:
    _MOD_LOADED = False
    _MOD_ERROR = str(e)


@unittest.skipUnless(_MOD_LOADED, "clio-transcribe module could not be loaded")
class TestFindAudioFiles(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "audio.mp3").write_bytes(b"fake mp3")
        (self.tmp / "recording.wav").write_bytes(b"fake wav")
        (self.tmp / "audio_TRANSKRIPT.md").write_text("transcript")
        (self.tmp / "document.pdf").write_bytes(b"fake pdf")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_finds_audio_formats(self):
        result = mod.find_audio_files(self.tmp)
        names = [f.name for f in result]
        self.assertIn("audio.mp3", names)
        self.assertIn("recording.wav", names)

    def test_excludes_transcript_files(self):
        result = mod.find_audio_files(self.tmp)
        names = [f.name for f in result]
        self.assertNotIn("audio_TRANSKRIPT.md", names)

    def test_excludes_non_audio(self):
        result = mod.find_audio_files(self.tmp)
        names = [f.name for f in result]
        self.assertNotIn("document.pdf", names)

    def test_recursive(self):
        sub = self.tmp / "sub"
        sub.mkdir()
        (sub / "nested.mp3").write_bytes(b"fake")
        flat = mod.find_audio_files(self.tmp, recursive=False)
        deep = mod.find_audio_files(self.tmp, recursive=True)
        self.assertGreater(len(deep), len(flat))


@unittest.skipUnless(_MOD_LOADED, "clio-transcribe module could not be loaded")
class TestFormatTime(unittest.TestCase):

    def test_seconds_only(self):
        self.assertEqual(mod._format_time(65), "01:05")

    def test_zero(self):
        self.assertEqual(mod._format_time(0), "00:00")

    def test_hours(self):
        self.assertEqual(mod._format_time(3661), "01:01:01")

    def test_under_minute(self):
        self.assertEqual(mod._format_time(45), "00:45")

    def test_exactly_one_hour(self):
        self.assertEqual(mod._format_time(3600), "01:00:00")


@unittest.skipUnless(_MOD_LOADED, "clio-transcribe module could not be loaded")
class TestTranscribeMocked(unittest.TestCase):
    """Tests transcribe() with mocked WhisperModel – no model download needed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _make_mock_model(self):
        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end   = 2.5
        mock_segment.text  = "This is a test transcription."

        mock_info = MagicMock()
        mock_info.language             = "en"
        mock_info.language_probability = 0.99

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        return mock_model

    def test_creates_transcript_file(self):
        audio = self.tmp / "test.mp3"
        audio.write_bytes(b"\xff\xfb" + b"\x00" * 100)

        with patch("faster_whisper.WhisperModel", return_value=self._make_mock_model()):
            ok, transcript_file, msg = mod.transcribe(audio, "cpu", "int8", "en")

        self.assertTrue(ok, f"transcribe() failed: {msg}")
        self.assertTrue(transcript_file.exists())

    def test_transcript_contains_text(self):
        audio = self.tmp / "test.mp3"
        audio.write_bytes(b"\xff\xfb" + b"\x00" * 100)

        with patch("faster_whisper.WhisperModel", return_value=self._make_mock_model()):
            ok, transcript_file, msg = mod.transcribe(audio, "cpu", "int8", "en")

        content = transcript_file.read_text(encoding="utf-8")
        self.assertIn("test transcription", content)
        self.assertIn("00:00", content)

    def test_skips_existing_transcript(self):
        audio = self.tmp / "test.mp3"
        audio.write_bytes(b"\xff\xfb" + b"\x00" * 100)
        existing = self.tmp / "test_TRANSKRIPT.md"
        existing.write_text("already exists")

        ok, _, msg = mod.transcribe(audio, "cpu", "int8", "en")
        self.assertFalse(ok)
        self.assertIn("Skipping", msg)

    def test_non_ascii_path_uses_temp(self):
        folder = self.tmp / "Göteborg"
        folder.mkdir()
        audio = folder / "inspelning.mp3"
        audio.write_bytes(b"\xff\xfb" + b"\x00" * 100)

        with patch("faster_whisper.WhisperModel", return_value=self._make_mock_model()):
            ok, transcript_file, msg = mod.transcribe(audio, "cpu", "int8", "sv")

        self.assertTrue(ok, f"Should handle non-ASCII path: {msg}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
