"""
test_permissions.py — enhetstester för permissions + intervju-sammanfattning

Täcker de tre nya clio_service-routrarna:
  - _route_mail_permissions_json
  - _route_mail_permissions_update
  - _route_mail_interview_summarize

Inga nätverksanrop — Notion och Claude mockade.
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


_FAKE_MATRIX = {
    "emails": {
        "carl@capgemini.com": {
            "level": "coded",
            "accounts": ["clio", "ssf"],
            "telegram_id": None,
            "kodord_scope": ["iaf", "capssf"],
            "kodord_write": ["capssf"],
        },
        "ulrika@arvas.se": {
            "level": "write",
            "accounts": [],
            "telegram_id": None,
            "kodord_scope": [],
            "kodord_write": [],
        },
    },
    "telegram_ids": {},
    "blocks": [],
}


# ── Hjälp: ladda routes från clio_service utan att starta servern ────────────

def _load_routes():
    """Importerar route-funktionerna utan att köra HTTP-servern."""
    import importlib
    # Mocka config + dotenv innan import
    with patch("clio_service._get_config") as mock_cfg:
        cfg = configparser.ConfigParser()
        cfg.add_section("mail")
        cfg.set("mail", "permissions_notion_page_id", "fake-page-id")
        cfg.set("mail", "notify_address", "test@arvas.international")
        mock_cfg.return_value = cfg
        import clio_service
        importlib.reload(clio_service)
    return clio_service


# ── 1. /mail/permissions/json ─────────────────────────────────────────────────

class TestPermissionsJson(unittest.TestCase):

    def setUp(self):
        self.cfg = configparser.ConfigParser()
        self.cfg.add_section("mail")
        self.cfg.set("mail", "permissions_notion_page_id", "fake-page-id")

    @patch("clio_service._get_config")
    @patch("clio_service.os.getenv", return_value="fake-token")
    @patch("clio_access.notion_source.fetch_matrix", return_value=_FAKE_MATRIX)
    def test_returns_ok_and_users_list(self, mock_fetch, mock_env, mock_cfg):
        mock_cfg.return_value = self.cfg
        import clio_service
        result = clio_service._route_mail_permissions_json({})
        self.assertTrue(result.get("ok"), f"Svar: {result}")
        self.assertIn("users", result)
        self.assertIsInstance(result["users"], list)

    @patch("clio_service._get_config")
    @patch("clio_service.os.getenv", return_value="fake-token")
    @patch("clio_access.notion_source.fetch_matrix", return_value=_FAKE_MATRIX)
    def test_user_structure(self, mock_fetch, mock_env, mock_cfg):
        mock_cfg.return_value = self.cfg
        import clio_service
        result = clio_service._route_mail_permissions_json({})
        users = {u["email"]: u for u in result["users"]}

        self.assertIn("carl@capgemini.com", users)
        carl = users["carl@capgemini.com"]
        self.assertEqual(carl["level"], "coded")
        self.assertEqual(carl["accounts"], ["clio", "ssf"])
        self.assertEqual(carl["kodord_scope"], ["iaf", "capssf"])
        self.assertEqual(carl["kodord_write"], ["capssf"])

    @patch("clio_service._get_config")
    def test_missing_page_id_returns_error(self, mock_cfg):
        cfg = configparser.ConfigParser()
        cfg.add_section("mail")
        mock_cfg.return_value = cfg
        import clio_service
        result = clio_service._route_mail_permissions_json({})
        self.assertFalse(result.get("ok"))
        self.assertIn("permissions_notion_page_id", result.get("error", ""))


# ── 2. /mail/permissions/update ───────────────────────────────────────────────

class TestPermissionsUpdate(unittest.TestCase):

    def setUp(self):
        self.cfg = configparser.ConfigParser()
        self.cfg.add_section("mail")
        self.cfg.set("mail", "permissions_notion_page_id", "fake-page-id")

    @patch("clio_service._get_config")
    @patch("clio_service.os.getenv", return_value="fake-token")
    @patch("clio_access.notion_source.update_user_permission", return_value=True)
    def test_update_calls_notion_and_returns_ok(self, mock_update, mock_env, mock_cfg):
        mock_cfg.return_value = self.cfg
        import clio_service
        result = clio_service._route_mail_permissions_update({
            "email":        "carl@capgemini.com",
            "level":        "coded",
            "accounts":     ["clio"],
            "kodord_scope": ["iaf", "capssf"],
            "kodord_write": ["capssf"],
        })
        self.assertTrue(result.get("ok"), f"Svar: {result}")
        self.assertIn("carl@capgemini.com", result.get("text", ""))
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs["email"], "carl@capgemini.com")
        self.assertEqual(call_kwargs["level"], "coded")

    @patch("clio_service._get_config")
    def test_missing_email_returns_error(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        import clio_service
        result = clio_service._route_mail_permissions_update({"level": "coded"})
        self.assertFalse(result.get("ok"))
        self.assertIn("email", result.get("error", ""))

    @patch("clio_service._get_config")
    @patch("clio_service.os.getenv", return_value="fake-token")
    @patch("clio_access.notion_source.update_user_permission", side_effect=Exception("Notion timeout"))
    def test_notion_error_returns_error(self, mock_update, mock_env, mock_cfg):
        mock_cfg.return_value = self.cfg
        import clio_service
        result = clio_service._route_mail_permissions_update({
            "email": "carl@capgemini.com",
            "level": "coded",
        })
        self.assertFalse(result.get("ok"))
        self.assertIn("Notion timeout", result.get("error", ""))


# ── 3. /mail/interview/summarize ──────────────────────────────────────────────

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
        # Verifiera att standardprompt skickades till Claude
        call_args = mock_anthropic_cls.return_value.messages.create.call_args
        content = call_args[1]["messages"][0]["content"]
        self.assertIn("Sammanfatta", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
