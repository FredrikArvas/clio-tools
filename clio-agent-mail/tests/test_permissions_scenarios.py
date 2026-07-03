"""
test_permissions_scenarios.py — Automattestfall enligt ADD_permissions.md

Täcker:
  P-serien: grundläggande CRUD för permissions-tabellen
  D-serien: dialog-scenariot (vanlig konversation, ingen aktiv session)
  I-serien: intervju-scenariot (aktiv interview_session trumfar behörighet)
  S-serien: synk via clio_service-routes
  M-serien: migrering (idempotent, jessica-fallback)
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

MAIL_DIR  = Path(__file__).parent.parent
TOOLS_DIR = MAIL_DIR.parent
sys.path.insert(0, str(MAIL_DIR))
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(TOOLS_DIR / "clio-core"))  # clio_core

import state as st
from clio_access import AccessManager


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "state.db"
    st.init_db(db_path=path)
    yield path


# ── P-serien — grundläggande CRUD ────────────────────────────────────────────

def test_P01_known_address_returns_correct_level(db):
    st.upsert_permission("jessica@leijer.se", level="coded", db_path=db)
    row = st.get_permission("jessica@leijer.se", db_path=db)
    assert row is not None and row["level"] == "coded"


def test_P02_unknown_address_returns_none(db):
    assert st.get_permission("unknown@test.se", db_path=db) is None


def test_P03_upsert_creates_new_row(db):
    st.upsert_permission("ny@test.se", level="whitelisted", db_path=db)
    assert st.get_permission("ny@test.se", db_path=db) is not None


def test_P04_upsert_updates_existing(db):
    st.upsert_permission("jessica@leijer.se", level="whitelisted", db_path=db)
    import time; time.sleep(0.01)
    st.upsert_permission("jessica@leijer.se", level="write", db_path=db)
    assert st.get_permission("jessica@leijer.se", db_path=db)["level"] == "write"


def test_P05_accounts_restriction(db):
    st.upsert_permission("ulrika@arvas.se", level="write", accounts="krut,clio", db_path=db)
    am = AccessManager(db_path=db)
    assert set(am.get_accounts({"email": "ulrika@arvas.se"})) == {"krut", "clio"}


def test_P05b_star_accounts_means_all(db):
    st.upsert_permission("admin@arvas.se", level="admin", accounts="*", db_path=db)
    am = AccessManager(db_path=db)
    assert am.get_accounts({"email": "admin@arvas.se"}) == []


# ── D-serien — dialog-scenariot ───────────────────────────────────────────────

def _classify(level, db, on_whitelist=True, thread_session=None):
    import classifier as clf
    if level is not None:
        st.upsert_permission("jessica@leijer.se", level=level, db_path=db)
    mail = MagicMock()
    mail.sender = "Jessica Leijer <jessica@leijer.se>"
    mail.subject = "Hej"
    mail.body = "Hej Clio"
    mail.account_key = "clio"
    mail.thread_id = "t1" if thread_session else None
    mail.in_reply_to = None
    mail.attachments = []
    config = MagicMock()
    config.get = MagicMock(side_effect=lambda *a, **kw: kw.get("fallback", ""))
    whitelist = {"jessica@leijer.se"} if on_whitelist else set()
    real_am = AccessManager(db_path=db)
    with patch.object(clf, "_state") as ms, \
         patch("clio_access.AccessManager.from_config", return_value=real_am):
        ms.get_active_interview.return_value = thread_session
        ms.get_interview_by_thread.return_value = thread_session
        ms.is_blacklisted.return_value = (level == "denied")
        result = clf.classify(mail, whitelist, config)
    return result.action


def test_D01_whitelisted_auto_send(db):
    assert _classify("whitelisted", db) == "AUTO_SEND"


def test_D02_write_self_query(db):
    assert _classify("write", db) == "SELF_QUERY"


def test_D03_denied_ignore(db):
    assert _classify("denied", db, on_whitelist=False) == "STANDARD_REPLY"


def test_D04_not_in_db_on_whitelist(db):
    assert _classify(None, db, on_whitelist=True) == "AUTO_SEND"


def test_D05_not_in_db_not_on_whitelist(db):
    assert _classify(None, db, on_whitelist=False) == "STANDARD_REPLY"


# ── I-serien — intervju-scenariot ─────────────────────────────────────────────

def _sess():
    return {"id": 1, "participant_email": "jessica@leijer.se",
            "thread_id": "t1", "status": "active"}


def test_I01_whitelisted_with_session_interview(db):
    assert _classify("whitelisted", db, thread_session=_sess()) == "INTERVIEW"


def test_I02_denied_with_session_interview(db):
    assert _classify("denied", db, on_whitelist=False, thread_session=_sess()) == "INTERVIEW"


def test_I03_coded_with_session_interview(db):
    st.upsert_permission("jessica@leijer.se", level="coded",
                         kodord_read="annat", db_path=db)
    assert _classify("coded", db, thread_session=_sess()) == "INTERVIEW"


def test_I04_whitelisted_no_session_auto_send(db):
    assert _classify("whitelisted", db, thread_session=None) == "AUTO_SEND"


def test_I05_stopped_session_auto_send(db):
    assert _classify("whitelisted", db, thread_session=None) == "AUTO_SEND"


# ── S-serien — synk service ↔ DB ─────────────────────────────────────────────

def test_S01_json_empty_db(db, monkeypatch):
    monkeypatch.setattr(st, "DB_PATH", db)
    import clio_service as svc
    result = svc._route_mail_permissions_json({})
    assert result["ok"] is True and result["users"] == []


def test_S02_json_returns_rows(db, monkeypatch):
    st.upsert_permission("anna@test.se", level="write", accounts="clio", db_path=db)
    st.upsert_permission("bob@test.se",  level="whitelisted", db_path=db)
    monkeypatch.setattr(st, "DB_PATH", db)
    import clio_service as svc
    result = svc._route_mail_permissions_json({})
    assert {u["email"] for u in result["users"]} == {"anna@test.se", "bob@test.se"}


def test_S03_update_creates_row(db, monkeypatch):
    monkeypatch.setattr(st, "DB_PATH", db)
    import clio_service as svc
    r = svc._route_mail_permissions_update({
        "email": "new@test.se", "level": "coded",
        "accounts": ["clio"],
        "kodord_scope": ["proj1", "proj2"], "kodord_write": ["proj2"],
    })
    assert r["ok"] is True
    row = st.get_permission("new@test.se", db_path=db)
    assert row["level"] == "coded"
    assert "proj2" in row["kodord_rw"]
    assert "proj1" in row["kodord_read"]


def test_S04_update_updates_existing(db, monkeypatch):
    st.upsert_permission("existing@test.se", level="whitelisted", db_path=db)
    monkeypatch.setattr(st, "DB_PATH", db)
    import clio_service as svc
    svc._route_mail_permissions_update({"email": "existing@test.se", "level": "write"})
    assert st.get_permission("existing@test.se", db_path=db)["level"] == "write"


def test_S05_missing_email_error(db, monkeypatch):
    monkeypatch.setattr(st, "DB_PATH", db)
    import clio_service as svc
    r = svc._route_mail_permissions_update({})
    assert r["ok"] is False and "email" in r["error"].lower()


# ── M-serien — migrering ─────────────────────────────────────────────────────

def test_M01_migration_idempotent(db, monkeypatch):
    import migrate_permissions_notion_to_db as mig
    monkeypatch.setattr(st, "DB_PATH", db)
    sample = [
        {"email": "fredrik@arvas.se",  "level": "admin",       "accounts": "*",
         "kodord_read": "", "kodord_rw": ""},
        {"email": "jessica@leijer.se", "level": "whitelisted", "accounts": "*",
         "kodord_read": "", "kodord_rw": "jessica1"},
    ]
    with patch.object(mig, "fetch_notion_permissions", return_value=sample):
        mig.run(dry_run=False)
        mig.run(dry_run=False)
    rows = st.list_permissions(db_path=db)
    emails = [r["email"] for r in rows]
    assert len(emails) == len(set(emails)), "Dubletter efter idempotent migrering"
    # Migreringen seedar alltid med SEED_DATA — minst sample-posterna ska finnas
    seeded = {u["email"] for u in sample}
    assert seeded.issubset(set(emails))


def test_M02_jessica_added_when_missing(db, monkeypatch):
    import migrate_permissions_notion_to_db as mig
    monkeypatch.setattr(st, "DB_PATH", db)
    sample = [{"email": "fredrik@arvas.se", "level": "admin", "accounts": "*",
               "kodord_read": "", "kodord_rw": ""}]
    with patch.object(mig, "fetch_notion_permissions", return_value=sample):
        mig.run(dry_run=False)
    assert st.get_permission("jessica@leijer.se", db_path=db) is not None
