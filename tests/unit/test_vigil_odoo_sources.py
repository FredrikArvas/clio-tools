"""
Regressionstest: clio.vigil.source saknar fälten lang/country.

Fältet har återinförts flera gånger (2026-08-14, 2026-10-19, 2026-11-08) och
gett "Invalid field 'lang' on 'clio.vigil.source'" → hela insamlingen kraschar.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clio-vigil"))

import odoo_writer  # noqa: E402

FORBIDDEN_FIELDS = {"lang", "country"}


class FakeModel:
    """Minimal ersättare för odoo_env['clio.vigil.source']."""

    def __init__(self, rows=None, fail_on_create=False):
        self.rows = rows or []
        self.fail_on_create = fail_on_create
        self.requested_fields = []
        self.created = []
        self.written = []

    def search_read(self, domain, fields=None, **kwargs):
        self.requested_fields.append(set(fields or []))
        bad = FORBIDDEN_FIELDS & set(fields or [])
        if bad:
            raise RuntimeError(f"Invalid field {sorted(bad)[0]!r} on 'clio.vigil.source'")
        return self.rows if "domain" in str(domain) else []

    def create(self, vals):
        if self.fail_on_create:
            raise RuntimeError("Odoo nere")
        bad = FORBIDDEN_FIELDS & set(vals)
        if bad:
            raise RuntimeError(f"Invalid field {sorted(bad)[0]!r} on 'clio.vigil.source'")
        self.created.append(vals)
        return 1

    def write(self, ids, vals):
        self.written.append(vals)
        return True


class FakeEnv(dict):
    pass


def _env(model):
    env = FakeEnv()
    env["clio.vigil.source"] = model
    return env


def test_write_sources_google_news_skickar_inte_lang_country():
    model = FakeModel(rows=[])
    sources = [{
        "name": "GN ufo", "domain": "ufo", "source_type": "google_news",
        "query": "uap disclosure", "lang": "en", "country": "US",
    }]
    odoo_writer.write_sources(_env(model), sources)
    assert model.created, "källan skulle ha skapats"
    assert not (FORBIDDEN_FIELDS & set(model.created[0]))
    assert model.created[0]["google_news_query"] == "uap disclosure"


def test_read_sources_begar_inte_lang_country():
    rows = [{
        "name": "Källa", "source_type": "rss", "url": "https://example.org/feed",
        "channel_id": False, "google_news_query": False, "language": "en",
        "maturity": "tidig", "weight": 1.0, "transcription_threshold": 0.0,
        "auth_env": False, "archive_enabled": False,
    }]
    model = FakeModel(rows=rows)
    result = odoo_writer.read_sources(_env(model), "ufo")
    assert len(result) == 1
    assert all(not (FORBIDDEN_FIELDS & f) for f in model.requested_fields)


def test_read_sources_utan_odoo_ger_tom_lista():
    assert odoo_writer.read_sources(None, "ufo") == []


def test_write_sources_odoo_fel_kraschar_inte():
    model = FakeModel(rows=[], fail_on_create=True)
    sources = [{"name": "X", "domain": "ufo", "source_type": "rss", "url": "https://e.org"}]
    # Felet ska loggas per källa, inte bubbla upp och stoppa körningen
    assert odoo_writer.write_sources(_env(model), sources) == 0
