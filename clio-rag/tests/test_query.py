"""
Tester för query.py — testar källhänvisningsformatering och Claude-integrationen
utan att kräva Qdrant eller Anthropic API.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from query import format_context, print_sources


# ---------------------------------------------------------------------------
# Hjälp: skapa mock-hits
# ---------------------------------------------------------------------------

def make_hit(title: str, page_start: int, page_end: int, summary: str, score: float = 0.9):
    hit = MagicMock()
    hit.score = score
    hit.payload = {
        "title":          title,
        "summary":        summary,
        "ext_page_start": page_start,
        "ext_page_end":   page_end,
    }
    return hit


# ---------------------------------------------------------------------------
# format_context
# ---------------------------------------------------------------------------

def test_format_context_includes_title():
    hits = [make_hit("Ovillkorlig", 47, 48, "Kärlek är grunden.")]
    ctx = format_context(hits)
    assert "Ovillkorlig" in ctx


def test_format_context_includes_page_range():
    hits = [make_hit("Ovillkorlig", 47, 48, "Text.")]
    ctx = format_context(hits)
    assert "s. 47–48" in ctx


def test_format_context_single_page():
    hits = [make_hit("Egenanställning", 12, 12, "Text.")]
    ctx = format_context(hits)
    assert "s. 12" in ctx


def test_format_context_no_page():
    hits = [make_hit("MBA", 0, 0, "Text.")]
    ctx = format_context(hits)
    assert "MBA" in ctx


def test_format_context_multiple_hits():
    hits = [
        make_hit("Ovillkorlig",    47, 48, "Text A."),
        make_hit("Egenanställning", 12, 12, "Text B."),
    ]
    ctx = format_context(hits)
    assert "Passage 1" in ctx
    assert "Passage 2" in ctx


def test_format_context_includes_summary():
    hits = [make_hit("Ovillkorlig", 47, 47, "Unik summaryttext XYZ123.")]
    ctx = format_context(hits)
    assert "Unik summaryttext XYZ123" in ctx


# ---------------------------------------------------------------------------
# ask_claude — testar att svaret returneras korrekt
# ---------------------------------------------------------------------------

def test_ask_claude_returns_text():
    from query import ask_claude

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Svaret är 42.")]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("query.anthropic.Anthropic", return_value=mock_client):
        result = ask_claude("Vad är svaret?", "Kontexttext här.")

    assert result == "Svaret är 42."


def test_ask_claude_passes_question_in_message():
    from query import ask_claude

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Svar.")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("query.anthropic.Anthropic", return_value=mock_client):
        ask_claude("Min specifika fråga", "Kontext.")

    call_kwargs = mock_client.messages.create.call_args
    messages    = call_kwargs.kwargs["messages"]
    assert any("Min specifika fråga" in str(m) for m in messages)


# ---------------------------------------------------------------------------
# embed_query — testar att vektorn returneras
# ---------------------------------------------------------------------------

def test_embed_query_returns_vector():
    from query import embed_query

    mock_resp = MagicMock()
    mock_resp.data = [MagicMock(embedding=[0.5] * 1536)]
    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_resp

    with patch("query.OpenAI", return_value=mock_client):
        vector = embed_query("Testfråga")

    assert len(vector) == 1536
    assert vector[0] == 0.5
