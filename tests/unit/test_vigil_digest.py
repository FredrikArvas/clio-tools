"""Digest-flödet i clio-vigil (2026-11-08).

Digesten skickade inget från 28 augusti: textposter (RSS/Google News) fick aldrig
någon summary, eftersom summarizern bara läste transkript, och digesten krävde
summary. Nu sammanfattas textposter med lång description, och digesten visar
description när summary saknas.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clio-vigil"))

import orchestrator  # noqa: E402
import notifier  # noqa: E402
import summarizer  # noqa: E402

LONG_TEXT = "Pentagon released new UAP files with radar data. " * 12   # ~600 tecken


@pytest.fixture
def conn(tmp_path):
    c = orchestrator.init_db(tmp_path / "vigil.db")
    yield c
    c.close()


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def _fake(item, text):
        calls.append(text)
        return f"SUMMARY {item['id']}"

    monkeypatch.setattr(summarizer, "_summarize_with_ollama", _fake)
    monkeypatch.setattr(summarizer, "_summarize_with_claude", _fake)
    return calls


def _add(conn, url, state="indexed", description=None, transcript_path=None,
         source_type="rss", published_at="2099-01-01T00:00:00+00:00"):
    item_id = orchestrator.upsert_item(conn, url=url, domain="ufo",
                                       source_type=source_type, title=f"Title {url}")
    conn.execute(
        "UPDATE vigil_items SET state=?, description=?, transcript_path=?, published_at=? "
        "WHERE id=?",
        (state, description, transcript_path, published_at, item_id),
    )
    conn.commit()
    return item_id


def _row(conn, item_id):
    return conn.execute("SELECT * FROM vigil_items WHERE id=?", (item_id,)).fetchone()


# --- summarizer ------------------------------------------------------------

def test_text_item_with_long_description_gets_summary_and_stays_indexed(conn, fake_llm):
    item_id = _add(conn, "u1", description=LONG_TEXT)

    counts = summarizer.run_summarizer(conn, domain="ufo")

    assert counts["done"] == 1
    row = _row(conn, item_id)
    assert row["summary"] == f"SUMMARY {item_id}"
    assert row["state"] == "indexed"          # annars missar digesten den
    assert "Title u1" in fake_llm[0] and "radar data" in fake_llm[0]


def test_short_description_is_never_selected(conn, fake_llm):
    _add(conn, "u1", description="Pentagon UFO files - Fox News", source_type="google_news")

    counts = summarizer.run_summarizer(conn, domain="ufo")

    assert counts == {"done": 0, "failed": 0, "claude": 0, "ollama": 0}
    assert fake_llm == []


def test_html_entities_in_description_are_decoded(conn, fake_llm):
    _add(conn, "u1", description="&quot;Fire&quot; at Eagle&#39;s Nest. " + LONG_TEXT)

    summarizer.run_summarizer(conn, domain="ufo")

    assert "\"Fire\" at Eagle's Nest" in fake_llm[0]


def test_transcribed_item_still_moves_to_summarized(conn, fake_llm, tmp_path):
    transcript = tmp_path / "t.json"
    transcript.write_text('[{"text": "hello"}, {"text": "world"}]', encoding="utf-8")
    item_id = _add(conn, "u1", state="transcribed", transcript_path=str(transcript))

    summarizer.run_summarizer(conn, domain="ufo")

    assert _row(conn, item_id)["state"] == "summarized"
    assert fake_llm == ["hello world"]


def test_failed_llm_leaves_item_without_summary(conn, monkeypatch):
    monkeypatch.setattr(summarizer, "_summarize_with_ollama", lambda item, text: None)
    monkeypatch.setattr(summarizer, "LOCAL_MODEL", "qwen2.5:3b")
    monkeypatch.setattr(summarizer, "CLAUDE_THRESHOLD", 2.0)

    def _claude_down(item, text):
        raise RuntimeError("API nere")
    monkeypatch.setattr(summarizer, "_summarize_with_claude", _claude_down)
    item_id = _add(conn, "u1", description=LONG_TEXT)

    counts = summarizer.run_summarizer(conn, domain="ufo")

    assert counts["failed"] == 1
    assert _row(conn, item_id)["summary"] is None
    assert _row(conn, item_id)["state"] == "indexed"


# --- notifier --------------------------------------------------------------

def test_digest_includes_indexed_items_without_summary(conn):
    with_text = _add(conn, "u1", description=LONG_TEXT)
    _add(conn, "u2", state="filtered_out", description=LONG_TEXT)
    _add(conn, "u3", description=LONG_TEXT, published_at="2000-01-01T00:00:00+00:00")

    items = notifier._fetch_digest_items(conn, domain="ufo")

    assert [i["id"] for i in items] == [with_text]


def test_blurb_prefers_summary():
    assert notifier._item_blurb({"summary": "S", "description": "D", "title": "T"}) == "S"


def test_blurb_falls_back_to_truncated_description():
    blurb = notifier._item_blurb({"summary": None, "description": LONG_TEXT, "title": "T"})
    assert blurb.startswith("Pentagon released")
    assert blurb.endswith("…")
    assert len(blurb) <= notifier.MAX_BLURB_CHARS + 2


def test_blurb_empty_when_description_repeats_title():
    item = {"summary": None, "title": "Pentagon UFO files - Fox News",
            "description": "Pentagon UFO files - Fox News"}
    assert notifier._item_blurb(item) == ""


def test_digest_body_without_blurb_has_no_placeholder():
    item = {"title": "T", "source_name": "S", "published_at": "2026-11-08",
            "source_maturity": "etablerad", "summary": None, "description": None,
            "url": "https://x"}
    _, plain, html = notifier.build_digest([item], "ufo")
    assert "(ingen sammanfattning)" not in plain
    assert "https://x" in plain and "https://x" in html


def test_digest_marks_items_notified(conn, monkeypatch):
    monkeypatch.setattr(notifier, "send_digest", lambda *a, **k: True)
    item_id = _add(conn, "u1", description=LONG_TEXT)

    counts = notifier.run_digest(conn, domain="ufo")

    assert counts == {"sent": 1, "items": 1}
    assert _row(conn, item_id)["state"] == "notified"


def test_failed_send_does_not_mark_notified(conn, monkeypatch):
    monkeypatch.setattr(notifier, "send_digest", lambda *a, **k: False)
    item_id = _add(conn, "u1", description=LONG_TEXT)

    counts = notifier.run_digest(conn, domain="ufo")

    assert counts["sent"] == 0
    assert _row(conn, item_id)["state"] == "indexed"
