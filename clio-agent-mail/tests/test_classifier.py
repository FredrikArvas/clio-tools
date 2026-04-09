"""
test_classifier.py — enhetstester för regelmotor (classifier.py)

Täcker alla kombinationer av konto / vitlista / ämneskod.
Inga nätverksanrop — allt mockat.
"""
import configparser
import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from classifier import (
    classify,
    extract_sender_email,
    ACTION_AUTO_SEND,
    ACTION_SEND_FOR_APPROVAL,
    ACTION_STANDARD_REPLY,
    ACTION_FAQ_CHECK,
)
from imap_client import MailItem


def _config():
    cfg = configparser.ConfigParser()
    cfg.add_section("mail")
    cfg.set("mail", "imap_user_clio", "clio@arvas.international")
    cfg.set("mail", "imap_user_info", "info@arvas.international")
    cfg.set("mail", "approval_keyword_yes", "JA")
    cfg.set("mail", "approval_keyword_no", "NEJ")
    return cfg


def _mail(account, sender, subject="Hej", body="Test"):
    return MailItem(
        message_id="<test-123>",
        account=account,
        sender=sender,
        subject=subject,
        body=body,
        date_received="Mon, 6 Apr 2026 12:00:00 +0000",
        raw_uid="1",
    )


WHITELIST = {"kund@example.com", "partner@foretag.se"}


class TestExtractSenderEmail(unittest.TestCase):

    def test_extracts_from_angle_brackets(self):
        self.assertEqual(
            extract_sender_email("Kund Kundsson <kund@example.com>"),
            "kund@example.com",
        )

    def test_handles_bare_address(self):
        self.assertEqual(
            extract_sender_email("kund@example.com"),
            "kund@example.com",
        )

    def test_lowercases(self):
        self.assertEqual(
            extract_sender_email("Kund <KUND@EXAMPLE.COM>"),
            "kund@example.com",
        )


class TestClassifierClio(unittest.TestCase):

    def setUp(self):
        self.cfg = _config()

    # 1. Vitlistad + [CLIO-AUTO]
    def test_vitlistad_auto(self):
        mail = _mail("clio@arvas.international", "kund@example.com",
                     subject="[CLIO-AUTO] Uppdatering")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_AUTO_SEND)
        self.assertEqual(clf.account_key, "clio")

    # 2. Vitlistad + [CLIO-DRAFT]
    def test_vitlistad_draft(self):
        mail = _mail("clio@arvas.international", "kund@example.com",
                     subject="[CLIO-DRAFT] Offertfråga")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_SEND_FOR_APPROVAL)
        self.assertEqual(clf.account_key, "clio")

    # 3. Vitlistad utan ämneskod
    def test_vitlistad_ingen_kod(self):
        mail = _mail("clio@arvas.international", "kund@example.com",
                     subject="Vanlig fråga")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_SEND_FOR_APPROVAL)

    # 4. Ej vitlistad med [CLIO-AUTO] — ska ändå ge standardsvar
    def test_ej_vitlistad_med_auto_kod(self):
        mail = _mail("clio@arvas.international", "okand@spam.com",
                     subject="[CLIO-AUTO] Försök")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_STANDARD_REPLY)

    # 5. Ej vitlistad utan kod
    def test_ej_vitlistad_utan_kod(self):
        mail = _mail("clio@arvas.international", "okand@spam.com",
                     subject="Hej")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_STANDARD_REPLY)

    # 6. Ej vitlistad med [CLIO-DRAFT] — ska ändå ge standardsvar
    def test_ej_vitlistad_med_draft_kod(self):
        mail = _mail("clio@arvas.international", "inkräktare@evil.com",
                     subject="[CLIO-DRAFT] Försök till utnyttjande")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_STANDARD_REPLY)

    # 7. Vitlistad med visningsnamn i From-fältet
    def test_vitlistad_med_visningsnamn(self):
        mail = _mail("clio@arvas.international",
                     "Kund Kundsson <kund@example.com>",
                     subject="[CLIO-AUTO] Test")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_AUTO_SEND)

    # 8. Tom vitlista
    def test_tom_vitlista(self):
        mail = _mail("clio@arvas.international", "kund@example.com",
                     subject="[CLIO-AUTO] Test")
        clf = classify(mail, set(), self.cfg)
        self.assertEqual(clf.action, ACTION_STANDARD_REPLY)

    # 9. Okänt mottagarkonto — fallback
    def test_okant_konto_fallback(self):
        mail = _mail("okant@arvas.international", "kund@example.com")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_STANDARD_REPLY)


class TestClassifierInfo(unittest.TestCase):

    def setUp(self):
        self.cfg = _config()

    # 10. info@ → alltid FAQ_CHECK oavsett avsändare
    def test_info_konto_ger_faq_check(self):
        mail = _mail("info@arvas.international", "vem_som_helst@example.com")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_FAQ_CHECK)
        self.assertEqual(clf.account_key, "info")

    # 11. info@ med okänd avsändare — ska fortfarande ge FAQ_CHECK
    def test_info_okand_avsandare_faq_check(self):
        mail = _mail("info@arvas.international", "random@okand.org",
                     subject="Vad gör ni?")
        clf = classify(mail, set(), self.cfg)
        self.assertEqual(clf.action, ACTION_FAQ_CHECK)

    # 12. info@ case-insensitivitet på konto
    def test_info_konto_case_insensitive(self):
        mail = _mail("INFO@ARVAS.INTERNATIONAL", "kund@example.com")
        clf = classify(mail, WHITELIST, self.cfg)
        self.assertEqual(clf.action, ACTION_FAQ_CHECK)


if __name__ == "__main__":
    unittest.main()
