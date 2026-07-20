"""
test_audio_edit_transcribe.py
Unit tests för clio-audio-edit/transcribe.py

Täcker:
  - detect_language() returnerar (lang, conf)
  - transcribe() med language="auto" väljer KB-Whisper vid svenska
  - transcribe() med language="auto" väljer fallback-modell vid annat språk
  - transcribe() med explicit language="sv" är oförändrat
"""

import sys
import importlib.util
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ladda modulen direkt från clio-audio-edit/
_MOD_PATH = Path(__file__).parent.parent.parent / "clio-audio-edit" / "transcribe.py"

spec = importlib.util.spec_from_file_location("audio_edit_transcribe", _MOD_PATH)
mod = importlib.util.module_from_spec(spec)

# state-modulen behövs vid import — mocka den
_state_mock = MagicMock()
_state_mock.load_state.return_value = {}
_state_mock.save_state.return_value = None
sys.modules.setdefault("state", _state_mock)

try:
    spec.loader.exec_module(mod)
    _MOD_LOADED = True
except Exception as e:
    _MOD_LOADED = False
    _MOD_ERROR = str(e)


def _mock_model(lang: str = "sv", lang_prob: float = 0.97) -> MagicMock:
    seg = MagicMock()
    seg.start = 0.0
    seg.end   = 2.0
    seg.text  = "Teststycke."

    info = MagicMock()
    info.language             = lang
    info.language_probability = lang_prob

    model = MagicMock()
    model.transcribe.return_value = ([seg], info)
    return model


@unittest.skipUnless(_MOD_LOADED, f"Modul laddades inte: {locals().get('_MOD_ERROR', '')}")
class TestDetectLanguage(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.audio = self.tmp / "test.wav"
        self.audio.write_bytes(b"\x00" * 100)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_returnerar_språkkod_och_konfidens(self):
        with patch("faster_whisper.WhisperModel", return_value=_mock_model("sv", 0.95)):
            lang, conf = mod.detect_language(self.audio)
        self.assertEqual(lang, "sv")
        self.assertAlmostEqual(conf, 0.95)

    def test_engelska_detekteras(self):
        with patch("faster_whisper.WhisperModel", return_value=_mock_model("en", 0.99)):
            lang, conf = mod.detect_language(self.audio)
        self.assertEqual(lang, "en")


@unittest.skipUnless(_MOD_LOADED, f"Modul laddades inte: {locals().get('_MOD_ERROR', '')}")
class TestTranscribeAutoRoute(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.audio = self.tmp / "test.wav"
        self.audio.write_bytes(b"\x00" * 100)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _patch_all(self, detected_lang: str):
        """Patcharna täcker both WhisperModel-anrop: tiny (detect) + riktigt modell (transcribe)."""
        tiny_model  = _mock_model(detected_lang, 0.97)
        real_model  = _mock_model(detected_lang, 0.97)
        call_seq    = [tiny_model, real_model]

        def model_factory(*args, **kwargs):
            return call_seq.pop(0)

        return patch("faster_whisper.WhisperModel", side_effect=model_factory)

    def test_auto_svenska_använder_kb_whisper(self):
        used_model_ids = []

        def factory(model_id, **_):
            used_model_ids.append(model_id)
            return _mock_model("sv", 0.97)

        with patch("faster_whisper.WhisperModel", side_effect=factory), \
             patch.object(mod, "_audio_duration", return_value=10.0), \
             patch.object(mod, "_spinner_run", side_effect=lambda *a, **kw: a[1]()):
            mod.transcribe(self.audio, model_size="medium", language="auto")

        # Andra anropet (index 1) är den riktiga transkriberingen
        self.assertIn("KBLab/kb-whisper-medium", used_model_ids)

    def test_auto_engelska_använder_fallback(self):
        used_model_ids = []

        def factory(model_id, **_):
            used_model_ids.append(model_id)
            return _mock_model("en", 0.99)

        with patch("faster_whisper.WhisperModel", side_effect=factory), \
             patch.object(mod, "_audio_duration", return_value=10.0), \
             patch.object(mod, "_spinner_run", side_effect=lambda *a, **kw: a[1]()):
            mod.transcribe(self.audio, model_size="medium", language="auto")

        self.assertIn(mod._FALLBACK_MODEL, used_model_ids)
        self.assertNotIn("KBLab/kb-whisper-medium", used_model_ids)

    def test_explicit_sv_oförändrat(self):
        used_model_ids = []

        def factory(model_id, **_):
            used_model_ids.append(model_id)
            return _mock_model("sv", 0.97)

        with patch("faster_whisper.WhisperModel", side_effect=factory), \
             patch.object(mod, "_audio_duration", return_value=10.0), \
             patch.object(mod, "_spinner_run", side_effect=lambda *a, **kw: a[1]()):
            mod.transcribe(self.audio, model_size="medium", language="sv")

        # Bara ett anrop — ingen detektering
        self.assertEqual(len(used_model_ids), 1)
        self.assertIn("KBLab/kb-whisper-medium", used_model_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
