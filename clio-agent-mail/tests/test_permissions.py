"""
test_permissions.py — enhetstester för permissions-update + intervju-sammanfattning

Täcker:
  - /mail/permissions/update (valideringsfel)
  - _route_mail_interview_summarize

Behörighets-CRUD och service-synk täcks av test_permissions_scenarios.py (S-serien).
"""
import configparser
import sys
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import state


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


# ── /mail/permissions/update — validering ────────────────────────────────────

class TestPermissionsUpdate(unittest.TestCase):

    def setUp(self):
        self.cfg = configparser.ConfigParser()
        self.cfg.add_section("mail")

    @patch("clio_service._get_config")
    def test_missing_email_returns_error(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        import clio_service
        result = clio_service._route_mail_permissions_update({"level": "coded"})
        self.assertFalse(result.get("ok"))
        self.assertIn("email", result.get("error", ""))


# ── /mail/interview/summarize ─────────────────────────────────────────────────

class TestInterviewSummarize(unittest.TestCase):

    def setUp(self):
        self.db = _tmp_db()
        state.init_db(self.db)
        self.thread_id = "<thread-summarize-test>"
        state.save_mail(
            message_id="<out-s1>",
            account="clio@arvas.international",
            sender="clio@arvas.international",
            subject="Karriärsamtal",
            body="Vad är din bakgrund?",
            date_received="2026-04-27T09:00:00",
            thread_id=self.thread_id,
            direction="outbound",
            db_path=self.db,
        )
        state.save_mail(
            message_id="<in-s1>",
            account="clio@arvas.international",
            sender="carl@capgemini.com",
            subject="Re: Karriärsamtal",
            body="Jag har arbetat med IT-projekt i 12 år.",
            date_received="2026-04-27T10:00:00",
            thread_id=self.thread_id,
            direction="inbound",
            db_path=self.db,
        )

    def tearDown(self):
        try:
            self.db.unlink(missing_ok=True)
        except PermissionError:
            pass

    @patch("clio_service.os.getenv", return_value="fake-anthropic-key")
    @patch("state.get_thread_history")
    @patch("anthropic.Anthropic")
    def test_summarize_returns_text(self, mock_anthropic_cls, mock_history, mock_env):
        mock_history.return_value = [
            {"direction": "outbound", "body": "Vad är din bakgrund?",   "date_received": "2026-04-27T09:00:00"},
            {"direction": "inbound",  "body": "Jag har arbetat i 12 år.", "date_received": "2026-04-27T10:00:00"},
        ]
        fake_resp = MagicMock()
        fake_resp.content = [MagicMock(text="Carl har lång IT-erfarenhet.")]
        mock_anthropic_cls.return_value.messages.create.return_value = fake_resp

        import clio_service
        result = clio_service._route_mail_interview_summarize({
            "thread_id": self.thread_id,
            "prompt":    "Sammanfatta kortfattat.",
        })
        self.assertTrue(result.get("ok"), f"Svar: {result}")
        self.assertIn("Carl", result.get("text", ""))

    @patch("state.get_thread_history", return_value=[])
    def test_empty_thread_returns_error(self, mock_history):
        import clio_service
        result = clio_service._route_mail_interview_summarize({"thread_id": "<empty>"})
        self.assertFalse(result.get("ok"))

    def test_missing_thread_id_returns_error(self):
        import clio_service
        result = clio_service._route_mail_interview_summarize({})
        self.assertFalse(result.get("ok"))
        self.assertIn("thread_id", result.get("error", ""))

    @patch("clio_service.os.getenv", return_value="fake-anthropic-key")
    @patch("state.get_thread_history")
    @patch("anthropic.Anthropic")
    def test_default_prompt_used_when_empty(self, mock_anthropic_cls, mock_history, mock_env):
        """Tom prompt ska ge ett standardvärde, inte krascha."""
        mock_history.return_value = [
            {"direction": "inbound", "body": "Svar på fråga.", "date_received": "2026-04-27T10:00:00"},
        ]
        fake_resp = MagicMock()
        fake_resp.content = [MagicMock(text="Sammanfattning.")]
        mock_anthropic_cls.return_value.messages.create.return_value = fake_resp

        import clio_service
        result = clio_service._route_mail_interview_summarize({"thread_id": self.thread_id})
        self.assertTrue(result.get("ok"), f"Svar: {result}")
        call_args = mock_anthropic_cls.return_value.messages.create.call_args
        content = call_args[1]["messages"][0]["content"]
        self.assertIn("Sammanfatta", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
