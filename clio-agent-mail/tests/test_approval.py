"""
test_approval.py — enhetstester för godkännandeflöde (approval.py)

Täcker build_approval_request och check_approvals med mockad state och IMAP.
"""
import configparser
import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from approval import build_approval_request, check_approvals
from imap_client import MailItem


def _config():
    cfg = configparser.ConfigParser()
    cfg.add_section("mail")
    cfg.set("mail", "imap_user_clio", "clio@arvas.international")
    cfg.set("mail", "imap_user_info", "info@arvas.international")
    cfg.set("mail", "imap_host", "mail.misshosting.com")
    cfg.set("mail", "imap_port", "993")
    cfg.set("mail", "imap_password_clio", "test-password")
    cfg.set("mail", "smtp_host", "mail.misshosting.com")
    cfg.set("mail", "smtp_port", "587")
    cfg.set("mail", "notify_address", "fredrik@arvas.se")
    cfg.set("mail", "approval_keyword_yes", "JA")
    cfg.set("mail", "approval_keyword_no", "NEJ")
    return cfg


def _mail(sender="kund@example.com", subject="[CLIO-DRAFT] Fråga"):
    return MailItem(
        message_id="<original-123>",
        account="clio@arvas.international",
        sender=sender,
        subject=subject,
        body="Hej, jag undrar om ert erbjudande.",
        date_received="Mon, 6 Apr 2026 12:00:00 +0000",
        raw_uid="1",
    )


def _pending_row(response=None):
    """Skapar en sqlite3.Row-liknande dict för pending approvals."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": 1,
        "mail_id": 42,
        "draft": "Hej kund, tack för ditt mail...",
        "approval_message_id": "<clio-approval-test-uuid@arvas.international>",
        "sent_at": "2026-04-06T12:00:00",
        "message_id": "<original-123>",
        "account": "clio@arvas.international",
        "sender": "kund@example.com",
        "subject": "[CLIO-DRAFT] Fråga",
        "body": "Hej, jag undrar om ert erbjudande.",
        "fredrik_cc": None,
    }[key]
    return row


class TestBuildApprovalRequest(unittest.TestCase):

    def setUp(self):
        self.cfg = _config()
        self.mail = _mail()

    def test_subject_innehaller_avsandare(self):
        subject, body = build_approval_request(self.mail, "Utkastsvar", self.cfg)
        self.assertIn("kund@example.com", subject)

    def test_subject_innehaller_prefix(self):
        subject, body = build_approval_request(self.mail, "Utkastsvar", self.cfg)
        self.assertIn("[CLIO-GODKÄNN]", subject)

    def test_body_innehaller_ja_nej(self):
        subject, body = build_approval_request(self.mail, "Utkastsvar", self.cfg)
        self.assertIn("JA", body)
        self.assertIn("NEJ", body)

    def test_body_innehaller_draft(self):
        draft = "Hej kund, tack för din fråga..."
        subject, body = build_approval_request(self.mail, draft, self.cfg)
        self.assertIn(draft, body)

    def test_body_innehaller_originalmail(self):
        subject, body = build_approval_request(self.mail, "draft", self.cfg)
        self.assertIn(self.mail.body, body)

    def test_lang_body_trunkeras(self):
        lang_mail = _mail()
        lang_mail = MailItem(
            message_id=lang_mail.message_id,
            account=lang_mail.account,
            sender=lang_mail.sender,
            subject=lang_mail.subject,
            body="X" * 3000,
            date_received=lang_mail.date_received,
            raw_uid=lang_mail.raw_uid,
        )
        subject, body = build_approval_request(lang_mail, "draft", self.cfg)
        self.assertIn("...", body)


class TestCheckApprovals(unittest.TestCase):

    def setUp(self):
        self.cfg = _config()

    # Godkännandeflöde JA
    @patch("approval.state")
    @patch("approval._find_response")
    def test_ja_skickar_svar_och_uppdaterar_status(self, mock_find, mock_state):
        mock_state.get_pending_approvals.return_value = [_pending_row()]
        mock_find.return_value = "JA"
        mock_state.STATUS_SENT = "SENT"

        smtp_mock = MagicMock()
        check_approvals(self.cfg, smtp_mock)

        smtp_mock.assert_called_once()
        call_kwargs = smtp_mock.call_args[1]
        self.assertEqual(call_kwargs["to_addr"], "kund@example.com")
        mock_state.update_status.assert_called_with("<original-123>", "SENT")
        mock_state.record_approval_response.assert_called_with(1, "JA")

    # Godkännandeflöde NEJ
    @patch("approval.state")
    @patch("approval._find_response")
    def test_nej_avbryter_utan_att_skicka(self, mock_find, mock_state):
        mock_state.get_pending_approvals.return_value = [_pending_row()]
        mock_find.return_value = "NEJ"
        mock_state.STATUS_REJECTED = "REJECTED"

        smtp_mock = MagicMock()
        check_approvals(self.cfg, smtp_mock)

        smtp_mock.assert_not_called()
        mock_state.update_status.assert_called_with("<original-123>", "REJECTED")
        mock_state.record_approval_response.assert_called_with(1, "NEJ")

    # Inget svar ännu
    @patch("approval.state")
    @patch("approval._find_response")
    def test_inget_svar_gör_ingenting(self, mock_find, mock_state):
        mock_state.get_pending_approvals.return_value = [_pending_row()]
        mock_find.return_value = None

        smtp_mock = MagicMock()
        check_approvals(self.cfg, smtp_mock)

        smtp_mock.assert_not_called()
        mock_state.update_status.assert_not_called()

    # Inga pending godkännanden
    @patch("approval.state")
    def test_inga_pending_gör_ingenting(self, mock_state):
        mock_state.get_pending_approvals.return_value = []

        smtp_mock = MagicMock()
        check_approvals(self.cfg, smtp_mock)

        smtp_mock.assert_not_called()

    # dry_run blockerar sändning
    @patch("approval.state")
    @patch("approval._find_response")
    def test_dry_run_skickar_inte(self, mock_find, mock_state):
        mock_state.get_pending_approvals.return_value = [_pending_row()]
        mock_find.return_value = "JA"
        mock_state.STATUS_SENT = "SENT"

        smtp_mock = MagicMock()
        check_approvals(self.cfg, smtp_mock, dry_run=True)

        smtp_mock.assert_not_called()
        # Status ska ändå uppdateras i dry_run? Nej — state-skrivning sker inte heller.
        # check_approvals anropar state.update_status direkt, dry_run blockerar inte det.
        # Verifiera att record_approval_response anropas (det är en läsning/skrivning av svar)
        mock_state.record_approval_response.assert_called_with(1, "JA")


if __name__ == "__main__":
    unittest.main()
