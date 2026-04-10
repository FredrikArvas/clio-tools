"""
test_narrate_edge.py
System tests for clio-narrate-batch.py — requires internet + edge-tts.

Tests:
    - narrate_edge() produces a valid MP3 file
    - Invalid voice fails gracefully
"""

import sys
import unittest
import tempfile
import shutil
from pathlib import Path

import importlib.util
spec = importlib.util.spec_from_file_location(
    "clio_narrate",
    Path(__file__).parent.parent.parent / "clio-narrate" / "clio-narrate-batch.py"
)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    _MOD_LOADED = True
except Exception as e:
    _MOD_LOADED = False
    _MOD_ERROR = str(e)


@unittest.skipUnless(_MOD_LOADED, "clio-narrate module could not be loaded")
class TestNarrateEdge(unittest.TestCase):
    """Requires internet connection and edge-tts."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_edge_creates_mp3(self):
        try:
            import edge_tts
        except ImportError:
            self.skipTest("edge-tts not installed")

        out = self.tmp / "output.mp3"
        ok, msg = mod.narrate_edge(
            "Short test sentence.",
            out,
            "sv-SE-SofieNeural",
            "+0%"
        )
        self.assertTrue(ok, f"Edge-TTS failed: {msg}")
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)

    def test_edge_invalid_voice_fails_gracefully(self):
        try:
            import edge_tts
        except ImportError:
            self.skipTest("edge-tts not installed")

        out = self.tmp / "output.mp3"
        ok, msg = mod.narrate_edge(
            "Test",
            out,
            "xx-XX-InvalidVoice",
            "+0%"
        )
        self.assertFalse(ok)
        self.assertIn("EXCEPTION", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
