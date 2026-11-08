"""Transkriberingskön i clio-vigil: textartiklar ska aldrig hamna i Whisper.

Bakgrund: fallbacken i get_next_for_transcription plockade queued RSS utan
enclosure_url, download_audio hämtade artikelns HTML, Whisper gav 0 segment
och posten blev kvar i transcribing för alltid.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clio-vigil"))

import orchestrator  # noqa: E402

transcriber = pytest.importorskip("transcriber")


@pytest.fixture
def conn(tmp_path):
    c = orchestrator.init_db(tmp_path / "vigil.db")
    yield c
    c.close()


def _add(conn, url, state, source_type="rss", enclosure=None, priority=1.0):
    item_id = orchestrator.upsert_item(
        conn, url=url, domain="ufo", source_type=source_type,
        title=url, raw_metadata=json.dumps({"enclosure_url": enclosure}),
    )
    conn.execute("UPDATE vigil_items SET state = ?, priority_score = ? WHERE id = ?",
                 (state, priority, item_id))
    conn.commit()
    return item_id


def test_textartikel_valjs_inte_for_transkription(conn):
    _add(conn, "https://example.com/artikel", "queued", enclosure=None)
    assert orchestrator.get_next_for_transcription(conn, "ufo") is None


def test_nedladdat_ljud_valjs(conn):
    _add(conn, "https://example.com/text", "queued", enclosure=None, priority=9.0)
    pod = _add(conn, "https://example.com/pod", "downloaded", enclosure="https://x/a.mp3")
    row = orchestrator.get_next_for_transcription(conn, "ufo")
    assert row["id"] == pod


def test_strandad_med_segment_aterupptas(conn):
    item_id = _add(conn, "https://example.com/strandad", "transcribing")
    conn.execute("UPDATE vigil_items SET whisper_segment = 5 WHERE id = ?", (item_id,))
    conn.commit()
    assert orchestrator.get_next_for_transcription(conn, "ufo")["id"] == item_id


def test_download_audio_rss_utan_enclosure_hamtar_inget(monkeypatch):
    calls = []
    monkeypatch.setattr(transcriber, "_download_url", lambda u, p: calls.append(u) or True)
    item = {"id": 1, "source_type": "rss", "url": "https://example.com/artikel",
            "raw_metadata": json.dumps({"enclosure_url": None}), "title": "t",
            "published_at": None, "source_name": "s"}
    assert transcriber.download_audio(item) is None
    assert calls == []


def _run_transcribe(conn, monkeypatch, tmp_path, segments, shutdown):
    item_id = _add(conn, "https://example.com/pod", "downloaded", enclosure="https://x/a.mp3")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    conn.execute("UPDATE vigil_items SET audio_path = ? WHERE id = ?", (str(audio), item_id))
    conn.commit()
    monkeypatch.setattr(transcriber, "TRANSCRIPTS_DIR", tmp_path / "tr")
    monkeypatch.setattr(transcriber, "_transcribe_whisper_stream",
                        lambda *a, **k: (segments, False, "en", 0.99))
    monkeypatch.setattr(transcriber, "_shutdown_requested", shutdown)
    item = conn.execute("SELECT * FROM vigil_items WHERE id = ?", (item_id,)).fetchone()
    ok = transcriber.transcribe_item(conn, item_id, {"transcription_profile": "default"})
    state = conn.execute("SELECT state, error_message FROM vigil_items WHERE id = ?",
                         (item["id"],)).fetchone()
    return ok, state


def test_noll_segment_utan_sigterm_blir_failed(conn, monkeypatch, tmp_path):
    ok, state = _run_transcribe(conn, monkeypatch, tmp_path, [], shutdown=False)
    assert ok is False
    assert state["state"] == "failed"
    assert "0 segment" in state["error_message"]


def test_noll_segment_vid_sigterm_stannar_i_transcribing(conn, monkeypatch, tmp_path):
    ok, state = _run_transcribe(conn, monkeypatch, tmp_path, [], shutdown=True)
    assert ok is False
    assert state["state"] == "transcribing"


def test_segment_ger_transcribed(conn, monkeypatch, tmp_path):
    segs = [{"start": 0.0, "end": 1.0, "text": "hej"}]
    ok, state = _run_transcribe(conn, monkeypatch, tmp_path, segs, shutdown=False)
    assert ok is True
    assert state["state"] == "transcribed"


# --- Preemption ------------------------------------------------------------

def test_textartikel_i_queued_preempterar_inte(conn):
    pod = _add(conn, "https://example.com/pod", "transcribing", enclosure="https://x/a.mp3", priority=1.0)
    _add(conn, "https://example.com/text", "queued", enclosure=None, priority=9.0)
    assert transcriber._should_preempt(conn, pod, 1.0) is None


def test_nedladdat_med_hogre_prioritet_preempterar(conn):
    pod = _add(conn, "https://example.com/pod", "transcribing", enclosure="https://x/a.mp3", priority=1.0)
    other = _add(conn, "https://example.com/pod2", "downloaded", enclosure="https://x/b.mp3", priority=9.0)
    assert transcriber._should_preempt(conn, pod, 1.0) == other


def test_pausad_med_audio_gar_till_downloaded_och_aterupptas(conn):
    pod = _add(conn, "https://example.com/pod", "transcribing", enclosure="https://x/a.mp3")
    conn.execute("UPDATE vigil_items SET audio_path = '/tmp/a.mp3' WHERE id = ?", (pod,))
    conn.commit()
    orchestrator.preempt_current(conn, pod, reason="test", segment=50)
    row = conn.execute("SELECT state, whisper_segment FROM vigil_items WHERE id = ?", (pod,)).fetchone()
    assert (row["state"], row["whisper_segment"]) == ("downloaded", 50)
    assert orchestrator.get_next_for_transcription(conn, "ufo")["id"] == pod


def test_pausad_utan_audio_gar_till_queued(conn):
    pod = _add(conn, "https://example.com/pod", "transcribing", enclosure="https://x/a.mp3")
    orchestrator.preempt_current(conn, pod, reason="test", segment=50)
    state = conn.execute("SELECT state FROM vigil_items WHERE id = ?", (pod,)).fetchone()["state"]
    assert state == "queued"
