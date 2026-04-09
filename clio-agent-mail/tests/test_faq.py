"""
test_faq.py — enhetstester för FAQ-matchning (faq.py)

Mockar Claude API — inga riktiga anrop i tester.
"""
import configparser
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from faq import (
    match_faq,
    _parse_match_response,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_NONE,
    FAQMatch,
)
from imap_client import MailItem


def _config():
    cfg = configparser.ConfigParser()
    cfg.add_section("mail")
    cfg.set("mail", "faq_confidence_threshold", "high")
    return cfg


def _mail(subject="Fråga", body="Vad gör ni?"):
    return MailItem(
        message_id="<faq-test>",
        account="info@arvas.international",
        sender="kund@example.com",
        subject=subject,
        body=body,
        date_received="Mon, 6 Apr 2026 12:00:00 +0000",
        raw_uid="1",
    )


FAQ_ITEMS = [
    {"question": "Vad gör Arvas International?", "answer": "Vi erbjuder tjänster inom X och Y."},
    {"question": "Hur kontaktar jag Fredrik?", "answer": "fredrik@arvas.se eller 070-8145595"},
    {"question": "Vad kostar era tjänster?", "answer": "Kontakta oss för offert."},
]


def _mock_claude_response(text: str):
    """Bygger ett mock-svar som ser ut som anthropic.messages.create()."""
    mock_content = MagicMock()
    mock_content.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    return mock_response


class TestParseMatchResponse(unittest.TestCase):
    """Testar _parse_match_response() direkt utan API-anrop."""

    # 13. Hög konfidens med exakt matchning
    def test_high_confidence_match(self):
        text = (
            "CONFIDENCE: high\n"
            "MATCHED_QUESTION: Vad gör Arvas International?\n"
            "EXPLANATION: Frågan matchar tydligt FAQ-posten."
        )
        result = _parse_match_response(text, FAQ_ITEMS)
        self.assertEqual(result.confidence, CONFIDENCE_HIGH)
        self.assertEqual(result.question, "Vad gör Arvas International?")
        self.assertIn("X och Y", result.answer)

    # 14. Låg konfidens
    def test_low_confidence(self):
        text = (
            "CONFIDENCE: low\n"
            "MATCHED_QUESTION: Vad kostar era tjänster?\n"
            "EXPLANATION: Delvis matchning."
        )
        result = _parse_match_response(text, FAQ_ITEMS)
        self.assertEqual(result.confidence, CONFIDENCE_LOW)

    # 15. Ingen matchning
    def test_no_confidence(self):
        text = (
            "CONFIDENCE: none\n"
            "MATCHED_QUESTION: ingen\n"
            "EXPLANATION: Frågan faller utanför FAQ:n."
        )
        result = _parse_match_response(text, FAQ_ITEMS)
        self.assertEqual(result.confidence, CONFIDENCE_NONE)
        self.assertEqual(result.question, "")

    def test_invalid_confidence_falls_back_to_none(self):
        text = (
            "CONFIDENCE: medium\n"
            "MATCHED_QUESTION: Vad gör Arvas International?\n"
            "EXPLANATION: Okänt värde."
        )
        result = _parse_match_response(text, FAQ_ITEMS)
        self.assertEqual(result.confidence, CONFIDENCE_NONE)

    def test_empty_faq_list(self):
        result = _parse_match_response("CONFIDENCE: high\nMATCHED_QUESTION: test\nEXPLANATION: x", [])
        self.assertEqual(result.confidence, CONFIDENCE_NONE)


class TestMatchFaq(unittest.TestCase):
    """Testar match_faq() med mockad Claude API."""

    def setUp(self):
        self.cfg = _config()

    def test_returns_none_match_when_no_faq_items(self):
        mail = _mail()
        result = match_faq(mail, [], self.cfg)
        self.assertEqual(result.confidence, CONFIDENCE_NONE)
        self.assertIn("Inga FAQ-poster", result.explanation)

    @patch("faq.anthropic.Anthropic")
    def test_high_confidence_returned(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(
            "CONFIDENCE: high\n"
            "MATCHED_QUESTION: Vad gör Arvas International?\n"
            "EXPLANATION: Klar matchning."
        )

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            mail = _mail(body="Kan ni berätta vad ni gör?")
            result = match_faq(mail, FAQ_ITEMS, self.cfg)

        self.assertEqual(result.confidence, CONFIDENCE_HIGH)
        self.assertEqual(result.question, "Vad gör Arvas International?")

    @patch("faq.anthropic.Anthropic")
    def test_api_error_returns_none(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API-fel")

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            mail = _mail()
            result = match_faq(mail, FAQ_ITEMS, self.cfg)

        self.assertEqual(result.confidence, CONFIDENCE_NONE)
        self.assertIn("Tekniskt fel", result.explanation)


if __name__ == "__main__":
    unittest.main()
