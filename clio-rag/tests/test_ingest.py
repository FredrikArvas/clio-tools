"""
Tester för ingest.py — testar SHA-256-logik och omindexeringsstrategi
utan att kräva Qdrant, Docling eller OpenAI.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest import sha256_text, sha256_file, source_id_for_path, build_summary


# ---------------------------------------------------------------------------
# sha256_text
# ---------------------------------------------------------------------------

def test_sha256_text_consistent():
    assert sha256_text("hello") == sha256_text("hello")


def test_sha256_text_different():
    assert sha256_text("hello") != sha256_text("world")


def test_sha256_text_unicode():
    h = sha256_text("Ulrika Arvas — Ovillkorlig kärlek")
    assert len(h) == 64  # SHA-256 hex = 64 tecken


# ---------------------------------------------------------------------------
# source_id_for_path
# ---------------------------------------------------------------------------

def test_source_id_is_deterministic(tmp_path):
    p = tmp_path / "testbok.pdf"
    p.touch()
    assert source_id_for_path(p) == source_id_for_path(p)


def test_source_id_differs_for_different_paths(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.touch()
    b.touch()
    assert source_id_for_path(a) != source_id_for_path(b)


def test_source_id_is_valid_uuid(tmp_path):
    p = tmp_path / "test.pdf"
    p.touch()
    sid = source_id_for_path(p)
    # Kastar ValueError om ogiltigt UUID
    uuid.UUID(sid)


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------

def test_build_summary_truncates():
    long_text = "x" * 2000
    assert len(build_summary(long_text)) == 1200


def test_build_summary_short_text():
    text = "Kort text."
    assert build_summary(text) == "Kort text."


# ---------------------------------------------------------------------------
# Omindexeringsstrategi — get_existing_hashes + ingest_pdf
# ---------------------------------------------------------------------------

def test_ingest_pdf_skips_unchanged_chunks(tmp_path):
    """
    Om en chunk redan har rätt source_hash i Qdrant ska den inte upsertas igen.
    """
    # Skapa en minimal dummy-PDF (bara en fil, Docling mockas)
    pdf = tmp_path / "ovillkorlig.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")

    chunk_text = "Ovillkorlig kärlek är grunden."
    chunk_hash = sha256_text(chunk_text)
    source_id  = source_id_for_path(pdf)

    # Befintlig hash matchar → ingen upsert
    mock_client = MagicMock()
    mock_client.scroll.return_value = (
        [MagicMock(payload={"chunk_index": 0, "source_hash": chunk_hash})],
        None,  # no next_page
    )

    mock_chunk       = MagicMock()
    mock_chunk.text  = chunk_text
    mock_chunk.meta.doc_items = []

    mock_result   = MagicMock()
    mock_result.document = MagicMock()

    with (
        patch("ingest.get_qdrant_client", return_value=mock_client),
        patch("ingest.is_local_available", return_value=False),
        patch("docling.document_converter.DocumentConverter.convert", return_value=mock_result),
        patch("docling.chunking.HybridChunker.chunk", return_value=[mock_chunk]),
        patch("ingest.OpenAI") as mock_openai,
    ):
        from ingest import ingest_pdf
        count = ingest_pdf(pdf, force=False)

    # Ingen ny upsert — 0 nya chunks
    assert count == 0
    mock_client.upsert.assert_not_called()


def test_ingest_pdf_reindexes_changed_chunk(tmp_path):
    """
    Om source_hash skiljer sig ska chunken upsertas.
    """
    pdf = tmp_path / "ovillkorlig.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")

    chunk_text  = "Ny text som inte funnits förut."
    old_hash    = "gammal_hash_som_inte_stämmer"

    mock_client = MagicMock()
    mock_client.scroll.return_value = (
        [MagicMock(payload={"chunk_index": 0, "source_hash": old_hash})],
        None,
    )

    mock_embedding = MagicMock()
    mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
    mock_openai_instance = MagicMock()
    mock_openai_instance.embeddings.create.return_value = mock_embedding

    mock_chunk       = MagicMock()
    mock_chunk.text  = chunk_text
    mock_chunk.meta.doc_items = []

    mock_result          = MagicMock()
    mock_result.document = MagicMock()

    with (
        patch("ingest.get_qdrant_client", return_value=mock_client),
        patch("ingest.is_local_available", return_value=False),
        patch("docling.document_converter.DocumentConverter.convert", return_value=mock_result),
        patch("docling.chunking.HybridChunker.chunk", return_value=[mock_chunk]),
        patch("ingest.OpenAI", return_value=mock_openai_instance),
    ):
        from ingest import ingest_pdf
        count = ingest_pdf(pdf, force=False)

    assert count == 1
    mock_client.upsert.assert_called_once()
