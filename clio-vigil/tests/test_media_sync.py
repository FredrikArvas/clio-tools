"""
test_media_sync.py — Regressionstest: vigil_items → clio.media.article

Se REGRESSION_MEDIA_SYNC.md för fullständig specifikation.

Kör (från clio-vigil-katalogen på servern):
    python3 -m pytest tests/test_media_sync.py -v

Kräver:
    - Nätverksåtkomst mot https://uap.arvas.international
    - VIGIL_ODOO_URL / VIGIL_ODOO_DB / ODOO_USER / ODOO_PASSWORD i .env
    - clio_media och clio_vigil installerade i VIGIL_ODOO_DB (default: uap)

Testdata städas upp (URL-match på https://test.vigil/*) före och efter
varje modulkörning — ingen permanent påverkan på uap-databasen.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Lägg till clio-vigil-roten i sys.path
_VIGIL_ROOT = Path(__file__).parent.parent
_TOOLS_ROOT = _VIGIL_ROOT.parent
if str(_VIGIL_ROOT) not in sys.path:
    sys.path.insert(0, str(_VIGIL_ROOT))
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))


# ---------------------------------------------------------------------------
# Test-URLs — används som upsert-nyckel och städas upp vid behov
# ---------------------------------------------------------------------------

TEST_URLS = [
    "https://test.vigil/case-01-rss-article",
    "https://test.vigil/case-02-rss-podcast",
    "https://test.vigil/case-03-youtube-video",
    "https://test.vigil/case-04-null-published",
    "https://test.vigil/case-05-with-audio",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def odoo():
    """Ansluter till VIGIL_ODOO_DB (default: clio_media_test)."""
    from odoo_writer import get_odoo_env
    env = get_odoo_env()
    if env is None:
        pytest.skip("Odoo-anslutning ej tillgänglig — kontrollera .env och nätverksåtkomst")
    return env


@pytest.fixture(scope="module")
def vigil_conn():
    """In-memory SQLite med vigil_items-schema och 5 testposter."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE vigil_items (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            url               TEXT NOT NULL UNIQUE,
            domain            TEXT NOT NULL,
            source_type       TEXT NOT NULL,
            source_name       TEXT,
            source_maturity   TEXT DEFAULT 'tidig',
            title             TEXT,
            description       TEXT,
            published_at      TEXT,
            duration_seconds  INTEGER,
            relevance_score   REAL DEFAULT 0.0,
            priority_score    REAL DEFAULT 0.0,
            source_weight     REAL DEFAULT 1.0,
            state             TEXT DEFAULT 'discovered',
            state_updated_at  TEXT,
            transcript_path   TEXT,
            whisper_segment   INTEGER DEFAULT 0,
            whisper_model     TEXT DEFAULT 'medium',
            chroma_collection TEXT,
            indexed_at        TEXT,
            summary           TEXT,
            notified_at       TEXT,
            created_at        TEXT DEFAULT (datetime('now')),
            raw_metadata      TEXT,
            archive_downloaded INTEGER DEFAULT 0,
            archive_path      TEXT
        );
    """)

    rows = [
        # CASE-01: RSS-artikel, domän ufo
        dict(
            url="https://test.vigil/case-01-rss-article",
            domain="ufo",
            source_type="rss",
            source_name="Källa-01: source_name→source",
            source_maturity="etablerad",
            title="[CASE-01] media_type=article | data_source=vigil_ufo | state=indexed",
            published_at="2026-01-15T10:00:00+00:00",
            state="indexed",
            relevance_score=0.8500,
            priority_score=0.7200,
            summary="Sammanfattning case-01: body_snippet hämtas härifrån.",
            raw_metadata=json.dumps({"feed_url": "https://test.vigil/feed01.xml"}),
            created_at="2026-01-14T08:00:00",
        ),
        # CASE-02: RSS-podcast med enclosure
        dict(
            url="https://test.vigil/case-02-rss-podcast",
            domain="ufo",
            source_type="rss",
            source_name="Källa-02: podcast-källa",
            source_maturity="tidig",
            title="[CASE-02] media_type=podcast | enclosure_url satt | duration=3600",
            published_at="2026-02-20T14:30:00+00:00",
            duration_seconds=3600,
            state="transcribed",
            relevance_score=0.6300,
            priority_score=0.5100,
            raw_metadata=json.dumps({"enclosure_url": "https://test.vigil/ep02.mp3"}),
            created_at="2026-02-19T10:00:00",
        ),
        # CASE-03: YouTube-video, domän ai
        dict(
            url="https://test.vigil/case-03-youtube-video",
            domain="ai",
            source_type="youtube",
            source_name="Källa-03: youtube-kanal",
            source_maturity="akademisk",
            title="[CASE-03] media_type=video | source_type=youtube | data_source=vigil_ai",
            published_at="2026-03-10T09:00:00+00:00",
            duration_seconds=1800,
            state="notified",
            relevance_score=0.9100,
            priority_score=0.4100,
            raw_metadata=json.dumps({}),
            created_at="2026-03-09T12:00:00",
        ),
        # CASE-04: published_at=NULL, fallback till created_at
        dict(
            url="https://test.vigil/case-04-null-published",
            domain="ufo",
            source_type="rss",
            source_name="Källa-04: ingen publiceringsdatum",
            source_maturity="tidig",
            title="[CASE-04] published=False | first_seen←created_at (ej today)",
            published_at=None,
            state="filtered_in",
            relevance_score=0.3000,
            priority_score=0.2000,
            raw_metadata=json.dumps({}),
            created_at="2026-04-05T08:00:00",
        ),
        # CASE-05: archive_path satt → audio_downloaded=True
        dict(
            url="https://test.vigil/case-05-with-audio",
            domain="ufo",
            source_type="rss",
            source_name="Källa-05: audio nedladdad",
            source_maturity="etablerad",
            title="[CASE-05] audio_downloaded=True | archive_path→audio_path",
            published_at="2026-05-01T12:00:00+00:00",
            state="queued",
            relevance_score=0.7700,
            priority_score=0.6500,
            archive_path="/audio/test/case-05-episode.mp3",
            raw_metadata=json.dumps({}),
            created_at="2026-04-30T09:00:00",
        ),
    ]

    for r in rows:
        cols = ", ".join(r.keys())
        placeholders = ", ".join(f":{k}" for k in r.keys())
        conn.execute(f"INSERT INTO vigil_items ({cols}) VALUES ({placeholders})", r)
    conn.commit()

    yield conn
    conn.close()


@pytest.fixture(scope="module", autouse=True)
def sync_to_odoo(odoo, vigil_conn):
    """Kör sync en gång för alla test i modulen. Städar upp före och efter."""
    from odoo_writer import sync_items_to_media

    Article = odoo["clio.media.article"]

    def _cleanup():
        existing = Article.search_read([("url", "in", TEST_URLS)], ["id"])
        if existing:
            Article.unlink([r["id"] for r in existing])

    _cleanup()

    all_states = [
        r["state"]
        for r in vigil_conn.execute("SELECT DISTINCT state FROM vigil_items").fetchall()
    ]
    n = sync_items_to_media(odoo, vigil_conn, states=all_states)
    assert n == 5, f"Förväntade 5 synkade poster, fick {n}"

    yield

    _cleanup()


def _get(odoo, url: str) -> dict:
    Article = odoo["clio.media.article"]
    rows = Article.search_read(
        [("url", "=", url)],
        [
            "url", "title", "source", "media_type", "published", "first_seen",
            "data_source", "body_snippet", "vigil_state", "duration_seconds",
            "relevance_score", "priority_score", "source_maturity",
            "audio_path", "audio_downloaded",
        ],
        limit=1,
    )
    assert rows, f"Post saknas i Odoo: {url}"
    return rows[0]


# ---------------------------------------------------------------------------
# CASE-01 — RSS-artikel
# ---------------------------------------------------------------------------

class TestCase01RssArticle:
    @pytest.fixture(autouse=True)
    def record(self, odoo):
        self.rec = _get(odoo, "https://test.vigil/case-01-rss-article")

    def test_title(self):
        assert "[CASE-01]" in self.rec["title"]

    def test_source(self):
        assert self.rec["source"] == "Källa-01: source_name→source"

    def test_media_type_article(self):
        assert self.rec["media_type"] == "article"

    def test_data_source_vigil_ufo(self):
        assert self.rec["data_source"] == "vigil_ufo"

    def test_published(self):
        assert self.rec["published"] == "2026-01-15 10:00:00"

    def test_first_seen_equals_published(self):
        assert self.rec["first_seen"] == "2026-01-15 10:00:00"

    def test_vigil_state(self):
        assert self.rec["vigil_state"] == "indexed"

    def test_relevance_score(self):
        assert abs(self.rec["relevance_score"] - 0.85) < 0.0001

    def test_priority_score(self):
        assert abs(self.rec["priority_score"] - 0.72) < 0.0001

    def test_source_maturity(self):
        assert self.rec["source_maturity"] == "etablerad"

    def test_body_snippet(self):
        assert "case-01" in (self.rec["body_snippet"] or "").lower()


# ---------------------------------------------------------------------------
# CASE-02 — RSS-podcast med enclosure
# ---------------------------------------------------------------------------

class TestCase02RssPodcast:
    @pytest.fixture(autouse=True)
    def record(self, odoo):
        self.rec = _get(odoo, "https://test.vigil/case-02-rss-podcast")

    def test_title(self):
        assert "[CASE-02]" in self.rec["title"]

    def test_media_type_podcast(self):
        assert self.rec["media_type"] == "podcast", (
            "Förväntat podcast (rss + enclosure_url) — kontrollera _media_type_from_row()"
        )

    def test_duration_seconds(self):
        assert self.rec["duration_seconds"] == 3600

    def test_data_source(self):
        assert self.rec["data_source"] == "vigil_ufo"

    def test_published(self):
        assert self.rec["published"] == "2026-02-20 14:30:00"

    def test_vigil_state(self):
        assert self.rec["vigil_state"] == "transcribed"

    def test_relevance_score(self):
        assert abs(self.rec["relevance_score"] - 0.63) < 0.0001


# ---------------------------------------------------------------------------
# CASE-03 — YouTube-video, domän ai
# ---------------------------------------------------------------------------

class TestCase03YoutubeVideo:
    @pytest.fixture(autouse=True)
    def record(self, odoo):
        self.rec = _get(odoo, "https://test.vigil/case-03-youtube-video")

    def test_title(self):
        assert "[CASE-03]" in self.rec["title"]

    def test_media_type_video(self):
        assert self.rec["media_type"] == "video", (
            "Förväntat video (source_type=youtube) — kontrollera _SOURCE_TYPE_TO_MEDIA"
        )

    def test_data_source_vigil_ai(self):
        assert self.rec["data_source"] == "vigil_ai", (
            "Förväntat vigil_ai (domain=ai) — kontrollera data_source-mappning"
        )

    def test_duration_seconds(self):
        assert self.rec["duration_seconds"] == 1800

    def test_published(self):
        assert self.rec["published"] == "2026-03-10 09:00:00"

    def test_vigil_state(self):
        assert self.rec["vigil_state"] == "notified"

    def test_source_maturity(self):
        assert self.rec["source_maturity"] == "akademisk"


# ---------------------------------------------------------------------------
# CASE-04 — Null published_at, fallback till created_at
# ---------------------------------------------------------------------------

class TestCase04NullPublished:
    @pytest.fixture(autouse=True)
    def record(self, odoo):
        self.rec = _get(odoo, "https://test.vigil/case-04-null-published")

    def test_title(self):
        assert "[CASE-04]" in self.rec["title"]

    def test_published_is_false(self):
        assert not self.rec["published"], (
            "published ska vara False/tom när published_at=NULL"
        )

    def test_first_seen_uses_created_at(self):
        assert self.rec["first_seen"] == "2026-04-05 08:00:00", (
            "first_seen ska vara created_at (2026-04-05), inte körningens datum"
        )

    def test_first_seen_is_not_today(self):
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        first_seen_date = (self.rec["first_seen"] or "")[:10]
        assert first_seen_date != today, (
            f"first_seen får inte vara today ({today}) — fallback till created_at saknas"
        )

    def test_vigil_state(self):
        assert self.rec["vigil_state"] == "filtered_in"


# ---------------------------------------------------------------------------
# CASE-05 — Audio nedladdad
# ---------------------------------------------------------------------------

class TestCase05WithAudio:
    @pytest.fixture(autouse=True)
    def record(self, odoo):
        self.rec = _get(odoo, "https://test.vigil/case-05-with-audio")

    def test_title(self):
        assert "[CASE-05]" in self.rec["title"]

    def test_audio_path(self):
        assert self.rec["audio_path"] == "/audio/test/case-05-episode.mp3"

    def test_audio_downloaded_computed(self):
        assert self.rec["audio_downloaded"] is True, (
            "audio_downloaded ska vara True när audio_path är satt (computed-fält)"
        )

    def test_published(self):
        assert self.rec["published"] == "2026-05-01 12:00:00"

    def test_vigil_state(self):
        assert self.rec["vigil_state"] == "queued"

    def test_data_source(self):
        assert self.rec["data_source"] == "vigil_ufo"
