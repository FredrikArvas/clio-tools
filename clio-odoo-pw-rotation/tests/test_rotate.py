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
    _lookup_script,
    _set_password_script,
    _summarize_stderr,
    _verify_script,
    parse_accounts,
    parse_databases,
    process_one,
    warn_missing_logins,
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

def test_dry_run_only_looks_up_and_never_sends_password():
    account = {"label": "ADMIN", "login": "admin", "password": "TopSecret!42"}
    stdout = f"{RESULT_PREFIX} FOUND id=2\n"
    with patch("rotate_passwords._run_shell", return_value=(0, stdout, "")) as mock_shell:
        row = process_one("container", "odoo19", "aiab", account, dry_run=True)
    assert mock_shell.call_count == 1
    sent_code = mock_shell.call_args[0][2]
    assert "TopSecret!42" not in sent_code
    assert "write(" not in sent_code
    assert row["status"] == "WOULD_CHANGE"


def test_dry_run_missing_login_returns_skipped():
    account = {"label": "FREDRIK", "login": "fredrik@example.com", "password": "pw"}
    stdout = f"{RESULT_PREFIX} SKIP: kontot finns inte\n"
    with patch("rotate_passwords._run_shell", return_value=(0, stdout, "")):
        row = process_one("container", "odoo19", "aiab19b", account, dry_run=True)
    assert row["status"] == "SKIPPED"
    assert "finns inte" in row["detail"]


def test_dry_run_missing_database_returns_fail():
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    stderr = 'psycopg2.OperationalError: FATAL:  database "nope" does not exist\n'
    with patch("rotate_passwords._run_shell", return_value=(1, "", stderr)):
        row = process_one("container", "odoo19", "nope", account, dry_run=True)
    assert row["status"] == "FAIL"
    assert "finns inte" in row["detail"]


# ── process_one: missing login (SKIP) ─────────────────────────────────────────

def test_missing_login_returns_skipped():
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    stdout = f"{RESULT_PREFIX} SKIP: kontot finns inte\n"
    with patch("rotate_passwords._run_shell", return_value=(0, stdout, "")) as mock_shell:
        row = process_one("container", "odoo19", "aiab", account, dry_run=False)
    assert row["status"] == "SKIPPED"
    # Ingen verifiering ska köras när kontot saknas
    assert mock_shell.call_count == 1


def test_warn_missing_logins_only_when_missing_everywhere():
    rows = [
        {"login": "admin", "status": "OK"},
        {"login": "fredrik@example.com", "status": "SKIPPED"},
        {"login": "fredrik@example.com", "status": "SKIPPED"},
        {"login": "x@example.com", "status": "SKIPPED"},
        {"login": "x@example.com", "status": "OK"},
    ]
    assert warn_missing_logins(rows) == ["fredrik@example.com"]


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


# ── Odoo 19-specifikt ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("make", [
    lambda: _lookup_script("admin"),
    lambda: _set_password_script("admin", "pw'x\"y"),
    lambda: _verify_script("admin", "pw'x\"y"),
])
def test_generated_scripts_are_valid_python(make):
    compile(make(), "<odoo-shell>", "exec")


def test_set_script_uses_write_not_set_password():
    script = _set_password_script("admin", "pw")
    assert "write({'password'" in script
    assert "_set_password(" not in script


def test_verify_script_uses_odoo19_credential_dict_and_with_user():
    script = _verify_script("admin", "pw")
    assert "'type': 'password'" in script
    assert "with_user(user)._check_credentials(credential" in script


def test_lookup_includes_archived_users():
    assert "active_test=False" in _lookup_script("admin")


def test_shell_command_order_is_odoo19():
    with patch("rotate_passwords.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        from rotate_passwords import _run_shell
        _run_shell("c", "aiab19b", "print(1)")
    cmd = mock_run.call_args[0][0]
    assert cmd[cmd.index("odoo") + 1] == "shell"
    assert "pw" not in " ".join(cmd)


def test_verification_shell_failure_gives_unverified_not_crash():
    account = {"label": "ADMIN", "login": "admin", "password": "pw"}
    side_effects = [(0, f"{RESULT_PREFIX} OK\n", ""), (1, "", "boom Error: x")]
    with patch("rotate_passwords._run_shell", side_effect=side_effects):
        row = process_one("container", "odoo19", "aiab", account, dry_run=False)
    assert row["status"] == "OK_UNVERIFIED"


def test_summarize_stderr_skips_startup_noise():
    stderr = (
        "2026-11-14 20:13:09,678 WARNING ? odoo.tools.config: missing --http-interface\n"
        "2026-11-14 20:13:09,678 INFO ? odoo: Odoo version 19.0\n"
        "TypeError: ResUsers._set_password() takes 1 positional argument but 2 were given\n"
    )
    assert _summarize_stderr(stderr).startswith("TypeError")
