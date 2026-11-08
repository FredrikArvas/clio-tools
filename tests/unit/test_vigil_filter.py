"""Relevansfiltret i clio-vigil: hela ord i stället för delsträngar, och omfiltrering.

Bakgrund (2026-11-08): delsträngsmatchning gav falska träffar ("nde" i "under",
"aaro" i "Aaron", "orb" i "orbit") och 727 Multiverse 5D-avsnitt låg i
filtered_out eftersom "alien" m.fl. saknades bland nyckelorden.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clio-vigil"))

import orchestrator  # noqa: E402
from filter import keyword_score, refilter_filtered_out, run_filter  # noqa: E402

KEYWORDS = {
    "primary": ["alien", "abduct", "area 51", "aaro", "uso"],
    "secondary": ["nde", "orb", "kryon"],
}
CONFIG = {
    "domain_id": "ufo",
    "relevance_threshold": 0.40,
    "min_duration_sec": 120,
    "max_duration_sec": 18000,
    "keywords": KEYWORDS,
    "sources": {"rss": [], "youtube_channels": []},
}


@pytest.mark.parametrize("text", [
    "Aliens over Arizona",
    "First abduction case",
    "Abducted in 1975",
    "Inside Area 51",
    "AARO report released",
    "A USO off the coast",
])
def test_helt_ord_och_bojning_ger_traff(text):
    assert keyword_score(text, KEYWORDS) >= 0.4


@pytest.mark.parametrize("text", [
    "Aaron Rodgers interview",
    "Abuso de poder",
    "Semester i Italien",
    "Understanding the orbit",
    "Andersson om väder",
])
def test_delstrang_ger_ingen_traff(text):
    assert keyword_score(text, KEYWORDS) == 0.0


def test_tom_text_ger_noll():
    assert keyword_score("", KEYWORDS) == 0.0


@pytest.fixture
def conn(tmp_path):
    c = orchestrator.init_db(tmp_path / "vigil.db")
    yield c
    c.close()


def _add(conn, url, title, state, duration=1800, source="Multiverse 5D Podcast"):
    item_id = orchestrator.upsert_item(
        conn, url=url, domain="ufo", source_type="rss", title=title, source_name=source,
    )
    conn.execute("UPDATE vigil_items SET state = ?, duration_seconds = ?, relevance_score = 0 WHERE id = ?",
                 (state, duration, item_id))
    conn.commit()
    return item_id


def _state(conn, item_id):
    return conn.execute("SELECT state FROM vigil_items WHERE id = ?", (item_id,)).fetchone()["state"]


def test_refilter_koar_det_som_nu_klarar_troskeln(conn):
    hit = _add(conn, "https://x/1", "Alien abduction in Brazil", "filtered_out")
    miss = _add(conn, "https://x/2", "Trigueirinho - Alertas", "filtered_out")
    counts = refilter_filtered_out(conn, CONFIG)
    assert counts == {"checked": 2, "requeued": 1, "per_source": {"Multiverse 5D Podcast": 1}}
    assert _state(conn, hit) == "queued"
    assert _state(conn, miss) == "filtered_out"
    assert conn.execute("SELECT count(*) FROM transcription_queue WHERE item_id = ?", (hit,)).fetchone()[0] == 1


def test_refilter_respekterar_langdfiltret(conn):
    short = _add(conn, "https://x/3", "Alien trailer", "filtered_out", duration=30)
    assert refilter_filtered_out(conn, CONFIG)["requeued"] == 0
    assert _state(conn, short) == "filtered_out"


def test_refilter_torrkorning_skriver_inget(conn):
    item_id = _add(conn, "https://x/4", "Alien abduction", "filtered_out")
    counts = refilter_filtered_out(conn, CONFIG, is_dry_run=True)
    assert counts["requeued"] == 1
    row = conn.execute("SELECT state, relevance_score FROM vigil_items WHERE id = ?", (item_id,)).fetchone()
    assert (row["state"], row["relevance_score"]) == ("filtered_out", 0)


def test_refilter_ror_inte_andra_states(conn):
    indexed = _add(conn, "https://x/5", "Alien abduction", "indexed")
    refilter_filtered_out(conn, CONFIG)
    assert _state(conn, indexed) == "indexed"


def test_run_filter_oforandrat_beteende(conn):
    keep = _add(conn, "https://x/6", "Area 51 whistleblower", "discovered")
    drop = _add(conn, "https://x/7", "Understanding orbits", "discovered")
    counts = run_filter(conn, CONFIG)
    assert counts["filtered_in"] == 1 and counts["filtered_out"] == 1
    assert _state(conn, keep) == "queued"
    assert _state(conn, drop) == "filtered_out"
