"""
test_interview.py — integrationstester för intervjudialogflödet

Tre lager testas:
  1. State   — trådlänkning, historikuppbyggnad, session-livscykel
  2. Routing — classifier returnerar ACTION_INTERVIEW för aktiv session
  3. Handler — _handle_interview skickar svar och sparar tråd-tur

Inga nätverksanrop — Claude och SMTP mockade.
SQLite körs mot :memory: via state.DB_PATH-patching.
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
from imap_client import MailItem


# ── Hjälpare ──────────────────────────────────────────────────────────────────

def _tmp_db():
    """Returnerar sökväg till en tillfällig SQLite-databas."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return Path(f.name)


def _mail(sender="frippe@capgemini.com", subject="Re: Karriärsamtal",
          body="Jag har jobbat med projektledning i 10 år.",
          in_reply_to="", references="", message_id="<reply-001>"):
    return MailItem(
        message_id=message_id,
        account="clio@arvas.international",
        sender=sender,
        subject=subject,
        body=body,
        date_received="Mon, 20 Apr 2026 10:00:00 +0000",
        raw_uid="42",
        in_reply_to=in_reply_to,
        references=references,
    )


def _config():
    cfg = configparser.ConfigParser()
    cfg.add_section("mail")
    cfg.set("mail", "imap_user_clio", "clio@arvas.international")
    cfg.set("mail", "imap_user_info", "info@arvas.international")
    cfg.set("mail", "accounts", "clio,info")
    return cfg


# ── 1. State-lager ────────────────────────────────────────────────────────────

class TestInterviewState(unittest.TestCase):

    def setUp(self):
        self.db = _tmp_db()
        state.init_db(self.db)

    def tearDown(self):
        try:
            self.db.unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows håller SQLite-filen öppen en kort stund

    def test_create_and_get_active_session(self):
        state.create_interview_session(
            thread_id="<thread-001>",
            participant_email="frippe@capgemini.com",
            db_path=self.db,
        )
        session = state.get_active_interview("frippe@capgemini.com", self.db)
        self.assertIsNotNone(session)
        self.assertEqual(session["thread_id"], "<thread-001>")
        self.assertEqual(session["status"], state.INTERVIEW_STATUS_ACTIVE)

    def test_stop_session_returns_none(self):
        state.create_interview_session("<thread-002>", "ulrika@arvas.se", db_path=self.db)
        state.stop_interview_session("<thread-002>", self.db)
        self.assertIsNone(state.get_active_interview("ulrika@arvas.se", self.db))

    def test_resolve_thread_id_via_in_reply_to(self):
        """Inkommande svar ska länkas till rätt tråd via In-Reply-To."""
        # Spara ursprungsmail (Clios öppningsfråga)
        state.save_mail(
            message_id="<opener-001>",
            account="clio@arvas.international",
            sender="clio@arvas.international",
            subject="Karriärsamtal",
            body="Berätta om din bakgrund.",
            date_received="2026-04-20T09:00:00",
            thread_id="<opener-001>",
            direction="outbound",
            db_path=self.db,
        )
        # Frippe svarar — In-Reply-To pekar på öppningsmail
        resolved = state.resolve_thread_id(
            in_reply_to="<opener-001>",
            references="",
            db_path=self.db,
        )
        self.assertEqual(resolved, "<opener-001>")

    def test_resolve_thread_id_falls_back_to_references(self):
        """Om In-Reply-To saknas ska References användas."""
        state.save_mail(
            message_id="<msg-x>",
            account="clio@arvas.international",
            sender="clio@arvas.international",
            subject="Test",
            body="...",
            date_received="2026-04-20T09:00:00",
            thread_id="<msg-x>",
            db_path=self.db,
        )
        resolved = state.resolve_thread_id("", "<msg-x> <other-id>", self.db)
        self.assertEqual(resolved, "<msg-x>")

    def test_get_thread_history_returns_chronological_turns(self):
        """Historiken ska innehålla inbound + outbound i rätt ordning."""
        tid = "<thread-hist>"
        state.save_mail(
            message_id="<out-1>",
            account="clio@arvas.international",
            sender="clio@arvas.international",
            subject="Fråga 1",
            body="Vad är din bakgrund?",
            date_received="2026-04-20T09:00:00",
            thread_id=tid,
            direction="outbound",
            db_path=self.db,
        )
        state.save_mail(
            message_id="<in-1>",
            account="clio@arvas.international",
            sender="frippe@capgemini.com",
            subject="Re: Fråga 1",
            body="Jag har jobbat i 10 år.",
            date_received="2026-04-20T10:00:00",
            thread_id=tid,
            direction="inbound",
            db_path=self.db,
        )
        history = state.get_thread_history(tid, self.db)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["direction"], "outbound")
        self.assertEqual(history[1]["direction"], "inbound")

    def test_save_outbound_interview_reply(self):
        """Utgående svar ska sparas med direction=outbound."""
        tid = "<thread-out>"
        state.save_outbound_interview_reply(
            thread_id=tid,
            account="clio@arvas.international",
            sender="clio@arvas.international",
            subject="Re: Intervju",
            body="Nästa fråga: vad är du stolt över?",
            message_id="<out-reply-1>",
            db_path=self.db,
        )
        history = state.get_thread_history(tid, self.db)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["direction"], "outbound")


# ── 2. Classifier-routing ─────────────────────────────────────────────────────

class TestInterviewClassifier(unittest.TestCase):

    def setUp(self):
        self.db = _tmp_db()
        state.init_db(self.db)
        self.config = _config()

    def tearDown(self):
        try:
            self.db.unlink(missing_ok=True)
        except PermissionError:
            pass

    @patch("classifier._get_permission", return_value="whitelisted")
    @patch("state.get_active_interview")
    def test_active_session_returns_interview_action(self, mock_session, mock_perm):
        from classifier import classify, ACTION_INTERVIEW
        mock_session.return_value = {"thread_id": "<t>", "status": "active"}
        mail = _mail()
        whitelist = {"frippe@capgemini.com"}
        clf = classify(mail, whitelist, self.config)
        self.assertEqual(clf.action, ACTION_INTERVIEW)

    @patch("classifier._get_permission", return_value="whitelisted")
    @patch("state.get_active_interview")
    def test_no_session_does_not_route_to_interview(self, mock_session, mock_perm):
        from classifier import classify, ACTION_INTERVIEW
        mock_session.return_value = None
        mail = _mail()
        whitelist = {"frippe@capgemini.com"}
        clf = classify(mail, whitelist, self.config)
        self.assertNotEqual(clf.action, ACTION_INTERVIEW)

    @patch("classifier._get_permission", return_value="whitelisted")
    @patch("state.get_active_interview")
    def test_interview_check_uses_lowercase_email(self, mock_session, mock_perm):
        """Versaler i avsändaradress ska normaliseras innan sessionslookup."""
        from classifier import classify
        mock_session.return_value = None
        mail = _mail(sender="Frippe Karlsson <FRIPPE@Capgemini.COM>")
        classify(mail, {"frippe@capgemini.com"}, self.config)
        called_with = mock_session.call_args[0][0]
        self.assertEqual(called_with, "frippe@capgemini.com")


# ── 3. Handler-flödet ─────────────────────────────────────────────────────────

class TestInterviewHandler(unittest.TestCase):

    def setUp(self):
        self.db = _tmp_db()
        state.init_db(self.db)
        self.config = _config()
        self.config.set("mail", "smtp_host", "localhost")
        self.config.set("mail", "smtp_port", "465")
        self.config.set("mail", "imap_password_clio", "secret")

        # Skapa aktiv session + tråd-historik
        self.thread_id = "<thread-handler-test>"
        state.create_interview_session(
            self.thread_id, "frippe@capgemini.com",
            account_key="clio", db_path=self.db,
        )
        state.save_outbound_interview_reply(
            thread_id=self.thread_id,
            account="clio@arvas.international",
            sender="clio@arvas.international",
            subject="Karriärsamtal",
            body="Berätta om din bakgrund.",
            message_id="<opener-handler>",
            db_path=self.db,
        )
        state.save_mail(
            message_id="<inbound-1>",
            account="clio@arvas.international",
            sender="frippe@capgemini.com",
            subject="Re: Karriärsamtal",
            body="Jag har jobbat i 10 år med projektledning.",
            date_received="2026-04-20T10:00:00",
            thread_id=self.thread_id,
            direction="inbound",
            db_path=self.db,
        )

    def tearDown(self):
        try:
            self.db.unlink(missing_ok=True)
        except PermissionError:
            pass

    @patch("handlers.smtp_client.send_email")
    @patch("handlers.reply_module.generate_interview_reply",
           return_value="Vad är du mest stolt över i din karriär?")
    @patch("handlers.state.update_status")
    @patch("handlers.state.save_outbound_interview_reply")
    @patch("handlers.state.get_thread_history")
    @patch("handlers.state.get_active_interview")
    def test_handler_sends_reply_and_saves_outbound(
        self, mock_session, mock_history, mock_save, mock_update,
        mock_generate, mock_smtp
    ):
        """_handle_interview ska skicka nästa fråga och spara den i tråd-historiken."""
        mock_session.return_value = {
            "thread_id": self.thread_id,
            "account_key": "clio",
            "system_prompt": "Du genomför en intervju.",
            "status": "active",
        }
        mock_history.return_value = [
            {"direction": "outbound", "sender": "clio@arvas.international",
             "body": "Berätta om din bakgrund.", "date_received": "2026-04-20T09:00:00"},
            {"direction": "inbound", "sender": "frippe@capgemini.com",
             "body": "Jag har jobbat i 10 år.", "date_received": "2026-04-20T10:00:00"},
        ]

        from handlers import _handle_interview
        clf = MagicMock()
        clf.account_key = "clio"
        mail = _mail(
            in_reply_to="<opener-handler>",
            message_id="<inbound-2>",
            body="Jag är stolt över en stor migrationslösning.",
        )
        _handle_interview(mail, clf, self.thread_id, self.config, dry_run=False)

        # SMTP ska ha kallats med rätt mottagare och genererat svar
        self.assertTrue(mock_smtp.called)
        call_kwargs = mock_smtp.call_args[1]
        self.assertEqual(call_kwargs["to_addr"], "frippe@capgemini.com")
        self.assertIn("Vad är du mest stolt", call_kwargs["body"])

        # Utgående svar ska sparas i tråd-historiken
        self.assertTrue(mock_save.called)
        save_kwargs = mock_save.call_args[1]
        self.assertEqual(save_kwargs["thread_id"], self.thread_id)
        self.assertIn("Vad är du mest stolt", save_kwargs["body"])

    @patch("handlers.smtp_client.send_email")
    @patch("handlers.reply_module.generate_interview_reply",
           return_value="Fallback svar")
    def test_handler_falls_back_when_no_session(self, mock_generate, mock_smtp):
        """Om sessionen saknas ska _handle_interview falla tillbaka till auto-hantering."""
        with patch("handlers.state.get_active_interview", return_value=None), \
             patch("handlers._handle_auto_send") as mock_auto:
            from handlers import _handle_interview
            clf = MagicMock()
            clf.account_key = "clio"
            mail = _mail(message_id="<no-session>")
            _handle_interview(mail, clf, "<no-thread>", self.config, dry_run=False)
            mock_auto.assert_called_once()

    @patch("handlers.smtp_client.send_email")
    @patch("handlers.reply_module.generate_interview_reply",
           return_value="Nästa fråga")
    @patch("handlers.state.get_active_interview")
    @patch("handlers.state.get_thread_history", return_value=[])
    @patch("handlers.state.save_outbound_interview_reply")
    @patch("handlers.state.update_status")
    def test_dry_run_does_not_send(
        self, mock_update, mock_save, mock_history, mock_session,
        mock_generate, mock_smtp
    ):
        """dry_run=True ska inte skicka mail eller spara utgående svar."""
        mock_session.return_value = {
            "thread_id": self.thread_id,
            "account_key": "clio",
            "system_prompt": "...",
            "status": "active",
        }
        from handlers import _handle_interview
        clf = MagicMock()
        clf.account_key = "clio"
        mail = _mail()
        _handle_interview(mail, clf, self.thread_id, self.config, dry_run=True)

        mock_smtp.assert_not_called()
        mock_save.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
