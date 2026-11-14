"""Inkrementell Odoo-synk i clio-vigil (2026-11-08).

Tidigare skrevs alla ~15 700 poster om till Odoo två gånger per körning. Nu spårar
SQLite-triggern vigil_items_changed ändringar i changed_at, och synken skickar bara
rader som ändrats sedan senaste stämpeln (plus en full synk per dygn).
"""
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clio-vigil"))

import orchestrator  # noqa: E402
import odoo_writer  # noqa: E402
from odoo_writer import sync_items_from_conn, sync_items_to_media  # noqa: E402


class FakeModel:
    def __init__(self, name, fail_urls=()):
        self.name = name
        self.records = {}
        self.writes = []
        self.fail_urls = set(fail_urls)

    def search_read(self, domain, fields, limit=None):
        url = domain[0][2]
        return [{"id": self.records[url]}] if url in self.records else []

    def write(self, ids, vals):
        self._check(vals)
        self.writes.append(vals["url"])

    def create(self, vals):
        self._check(vals)
        self.records[vals["url"]] = len(self.records) + 1
        self.writes.append(vals["url"])

    def _check(self, vals):
        if vals["url"] in self.fail_urls:
            raise RuntimeError("Wrong value for clio.vigil.item.language: 'fi'")


class FakeEnv(dict):
    def __init__(self, fail_urls=()):
        super().__init__({
            "clio.vigil.item": FakeModel("item", fail_urls),
            "clio.media.article": FakeModel("media"),
        })

    def reset_writes(self):
        for model in self.values():
            model.writes.clear()


@pytest.fixture
def conn(tmp_path):
    c = orchestrator.init_db(tmp_path / "vigil.db")
    yield c
    c.close()


def _add(conn, url, state="indexed"):
    item_id = orchestrator.upsert_item(conn, url=url, domain="ufo", source_type="rss", title=url)
    conn.execute("UPDATE vigil_items SET state = ? WHERE id = ?", (state, item_id))
    conn.commit()
    return item_id


def _sync(env, conn, is_full=False):
    # SQLite-tid har millisekundupplösning: håll isär ändringar och synkstämplar
    time.sleep(0.003)
    env.reset_writes()
    sync_items_from_conn(env, conn, is_full=is_full)
    sync_items_to_media(env, conn, is_full=is_full)
    time.sleep(0.003)
    return env["clio.vigil.item"].writes, env["clio.media.article"].writes


def test_andra_synken_skickar_bara_andrade(conn):
    env = FakeEnv()
    _add(conn, "https://x/1")
    _add(conn, "https://x/2")
    assert _sync(env, conn) == (["https://x/1", "https://x/2"], ["https://x/1", "https://x/2"])

    assert _sync(env, conn) == ([], [])

    conn.execute("UPDATE vigil_items SET summary = 'ny' WHERE url = 'https://x/2'")
    conn.commit()
    assert _sync(env, conn) == (["https://x/2"], ["https://x/2"])


def test_stampling_triggar_inte_andring(conn):
    env = FakeEnv()
    item_id = _add(conn, "https://x/1")
    _sync(env, conn)
    row = conn.execute("SELECT changed_at, odoo_item_synced_at FROM vigil_items WHERE id = ?",
                       (item_id,)).fetchone()
    assert row["odoo_item_synced_at"] >= row["changed_at"]


def test_nya_rader_synkas(conn):
    env = FakeEnv()
    _add(conn, "https://x/1")
    _sync(env, conn)
    _add(conn, "https://x/3")
    assert _sync(env, conn) == (["https://x/3"], ["https://x/3"])


def test_misslyckad_rad_forsoks_igen_och_media_utan_lank_forsoks_igen(conn):
    env = FakeEnv(fail_urls={"https://x/fi"})
    _add(conn, "https://x/fi")
    items, media = _sync(env, conn)
    assert items == [] and media == ["https://x/fi"]

    items, media = _sync(env, conn)
    assert media == ["https://x/fi"], "artikel utan vigil_item-länk ska försökas igen"

    env["clio.vigil.item"].fail_urls.clear()
    assert _sync(env, conn) == (["https://x/fi"], ["https://x/fi"])
    assert _sync(env, conn) == ([], [])


def test_full_synk_skickar_allt(conn):
    env = FakeEnv()
    _add(conn, "https://x/1")
    _sync(env, conn)
    assert _sync(env, conn, is_full=True) == (["https://x/1"], ["https://x/1"])


def test_full_synk_nar_intervallet_passerat(conn):
    env = FakeEnv()
    _add(conn, "https://x/1")
    _sync(env, conn)
    conn.execute("UPDATE vigil_meta SET value = '2000-01-01T00:00:00.000'")
    conn.commit()
    assert _sync(env, conn) == (["https://x/1"], ["https://x/1"])
    assert _sync(env, conn) == ([], [])


def test_tillstand_utanfor_sync_states_skickas_inte(conn):
    env = FakeEnv()
    _add(conn, "https://x/d", state="discovered")
    assert _sync(env, conn) == ([], [])


def test_databas_utan_trigger_ger_full_synk_utan_stamplar():
    legacy = sqlite3.connect(":memory:")
    legacy.row_factory = sqlite3.Row
    legacy.execute(
        "CREATE TABLE vigil_items (id INTEGER PRIMARY KEY, url TEXT, domain TEXT, source_type TEXT,"
        " source_name TEXT, title TEXT, state TEXT, published_at TEXT, created_at TEXT,"
        " summary TEXT, raw_metadata TEXT, transcript_path TEXT)"
    )
    legacy.execute("INSERT INTO vigil_items (url, domain, source_type, state) "
                   "VALUES ('https://x/1', 'ufo', 'rss', 'indexed')")
    env = FakeEnv()
    assert not odoo_writer._supports_incremental(legacy)
    sync_items_to_media(env, legacy)
    sync_items_to_media(env, legacy)
    assert env["clio.media.article"].writes == ["https://x/1", "https://x/1"]


def test_oforandrad_relevans_skrivs_inte(conn):
    from filter import _score_rows
    item_id = _add(conn, "https://x/1", state="filtered_out")
    _sync(FakeEnv(), conn)
    rows = conn.execute("SELECT id, title, description FROM vigil_items").fetchall()
    _score_rows(conn, rows, {"primary": ["ufo"]})
    before = conn.execute("SELECT changed_at FROM vigil_items WHERE id = ?", (item_id,)).fetchone()[0]
    _score_rows(conn, rows, {"primary": ["ufo"]})
    after = conn.execute("SELECT changed_at FROM vigil_items WHERE id = ?", (item_id,)).fetchone()[0]
    assert before == after
