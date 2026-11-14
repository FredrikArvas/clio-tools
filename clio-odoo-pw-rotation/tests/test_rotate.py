"""
test_rotate.py
pytest-tester för rotate_passwords. Rör aldrig riktiga databaser.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from rotate_passwords import (
    RESULT_PREFIX,
    _extract_result,
    _set_password_script,
    _verify_script,
    parse_accounts,
    parse_databases,
    process_one,
)


# ── parse_accounts ─────────────────────────────────────────────────────────────

def test_parse_accounts_valid():
    env = {
        "ROTATE_ADMIN_LOGIN": "admin",
        "ROTATE_ADMIN_PASSWORD": "Secret1!",
        "ROTATE_FREDRIK_LOGIN": "fredrik@example.com",
        "ROTATE_FREDRIK_PASSWORD": "Secret2!",
    }
    accounts = parse_accounts(env)
    assert len(accounts) == 2
    logins = {a["login"] for a in accounts}
    assert logins == {"admin", "fredrik@example.com"}


def test_parse_accounts_missing_password():
    env = {
        "ROTATE_ADMIN_LOGIN": "admin",
        # saknar ROTATE_ADMIN_PASSWORD
    }
    with pytest.raises(ValueError, match="ROTATE_ADMIN_PASSWORD"):
        parse_accounts(env)


def test_parse_accounts_empty():
    assert parse_accounts({}) == []


def test_parse_accounts_ignores_unrelated_keys():
    env = {
        "ODOO_URL": "http://localhost:8079",
        "ROTATE_X_LOGIN": "x@example.com",
        "ROTATE_X_PASSWORD": "pw",
    }
    accounts = parse_accounts(env)
    assert len(accounts) == 1
    assert accounts[0]["login"] == "x@example.com"


# ── parse_databases ────────────────────────────────────────────────────────────

def test_parse_databases_odoo19():
    env = {"ROTATE_DATABASES_19": "aiab, examensbyran, gsf"}
    dbs = parse_databases(env, "odoo19")
    assert dbs == ["aiab", "examensbyran", "gsf"]


def test_parse_databases_missing_key():
    assert parse_databases({}, "odoo19") == []


# ── _extract_result ────────────────────────────────────────────────────────────

def test_extract_result_found():
    stdout = "Odoo startup noise\n##CLIO## OK\nmore noise"
    assert _extract_result(stdout) == "OK"


def test_extract_result_not_found():
    assert _extract_result("only noise here") == ""


# ── process_one: dry-run ───────────────────────────────────────────────────────

def test_dry_run_does_not_call_docker():
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    with patch("rotate_passwords._run_shell") as mock_shell:
        row = process_one("container", "odoo19", "aiab", account, dry_run=True)
    mock_shell.assert_not_called()
    assert row["status"] == "DRY_RUN"


# ── process_one: missing login (SKIP) ─────────────────────────────────────────

def test_missing_login_returns_skipped():
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    stdout = f"{RESULT_PREFIX} SKIP: login not found\n"
    with patch("rotate_passwords._run_shell", return_value=(0, stdout, "")):
        row = process_one("container", "odoo19", "aiab", account, dry_run=False)
    assert row["status"] == "SKIPPED"


# ── process_one: docker exec failure ──────────────────────────────────────────

def test_docker_exec_failure_returns_fail():
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    with patch("rotate_passwords._run_shell", return_value=(1, "", "container not found")):
        row = process_one("container", "odoo19", "aiab", account, dry_run=False)
    assert row["status"] == "FAIL"
    assert "container not found" in row["detail"]


def test_timeout_returns_fail():
    import subprocess
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    with patch("rotate_passwords._run_shell", side_effect=subprocess.TimeoutExpired("cmd", 90)):
        row = process_one("container", "odoo19", "aiab", account, dry_run=False)
    assert row["status"] == "FAIL"
    assert "Timeout" in row["detail"]


# ── process_one: OK with verification ─────────────────────────────────────────

def test_successful_change_and_verification():
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    set_stdout = f"{RESULT_PREFIX} OK\n"
    verify_stdout = f"{RESULT_PREFIX} VERIFY_OK\n"
    side_effects = [(0, set_stdout, ""), (0, verify_stdout, "")]
    with patch("rotate_passwords._run_shell", side_effect=side_effects):
        row = process_one("container", "odoo19", "aiab", account, dry_run=False)
    assert row["status"] == "OK"


def test_ok_but_verification_fails():
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    set_stdout = f"{RESULT_PREFIX} OK\n"
    verify_stdout = f"{RESULT_PREFIX} VERIFY_FAIL: AccessDenied\n"
    side_effects = [(0, set_stdout, ""), (0, verify_stdout, "")]
    with patch("rotate_passwords._run_shell", side_effect=side_effects):
        row = process_one("container", "odoo19", "aiab", account, dry_run=False)
    assert row["status"] == "OK_UNVERIFIED"
    assert "VERIFY_FAIL" in row["detail"]


# ── script generation: lösenord inbäddas via repr() (injektionsskydd) ─────────

def test_password_uses_repr_in_set_script():
    pw = "pw'with'quotes"
    script = _set_password_script("admin", pw)
    assert repr(pw) in script


def test_password_uses_repr_in_verify_script():
    pw = 'pw"double"quotes'
    script = _verify_script("admin", pw)
    assert repr(pw) in script


def test_no_code_injection_in_set_script():
    malicious = "'); import os; os.system('id'); x=('"
    script = _set_password_script("admin", malicious)
    assert repr(malicious) in script
    assert "os.system" not in script.replace(repr(malicious), "")
