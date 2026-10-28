"""
test_research_v2.py — Enhetstester för research-pipeline v2, P0 (claude_runner, run_state).

Inga nätverksanrop och inget riktigt `claude`-anrop: subprocess ersätts av en fake-runner.
"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))

import claude_runner as cr  # noqa: E402
import run_state as rs  # noqa: E402


# ── claude_runner: miljö och kommando ─────────────────────────────────────────

def test_build_env_strips_api_keys_without_touching_input():
    base = {"ANTHROPIC_API_KEY": "sk-test", "ANTHROPIC_AUTH_TOKEN": "t", "PATH": "/usr/bin"}
    env = cr.build_env(base)
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["PATH"] == "/usr/bin"
    assert base["ANTHROPIC_API_KEY"] == "sk-test"


def test_build_command_analyst_has_no_tools_and_hides_user_settings():
    command = cr.build_command("analyst", cr.MODEL_ANALYST, system_prompt="Du är analytiker.")
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--tools") + 1] == ""
    assert "--allowedTools" not in command
    assert command[command.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in command
    assert command[command.index("--system-prompt") + 1] == "Du är analytiker."


def test_build_command_collector_gets_web_tools_only():
    command = cr.build_command("collector", cr.MODEL_COLLECTOR, max_turns=40)
    assert command[command.index("--tools") + 1] == "WebSearch,WebFetch"
    assert command[command.index("--max-turns") + 1] == "40"


def test_no_role_combines_file_reading_and_network():
    for tools in cr.ROLE_TOOLS.values():
        has_network = {"WebSearch", "WebFetch"} & set(tools)
        has_files = {"Read", "Write", "Edit", "Bash", "Glob", "Grep"} & set(tools)
        assert not (has_network and has_files)


def test_build_command_unknown_role_raises():
    with pytest.raises(ValueError):
        cr.build_command("hacker", cr.MODEL_ANALYST)


# ── claude_runner: tolkning av svar ───────────────────────────────────────────

def _json(**kwargs) -> str:
    data = {"is_error": False, "result": "Rapport", "session_id": "abc", "subtype": "success",
            "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.12}
    data.update(kwargs)
    return json.dumps(data)


def test_parse_output_ok():
    result = cr.parse_output(_json(), 0, "m")
    assert result.is_ok
    assert result.text == "Rapport"
    assert result.usage["output_tokens"] == 5
    assert result.cost_usd == pytest.approx(0.12)


def test_parse_output_usage_limit_becomes_limit():
    result = cr.parse_output(_json(is_error=True, result="You've hit your limit · resets 3pm"), 1)
    assert result.status == cr.STATUS_LIMIT


def test_parse_output_other_error_becomes_error():
    result = cr.parse_output(_json(is_error=True, subtype="error_max_turns", result=""), 1)
    assert result.status == cr.STATUS_ERROR
    assert "error_max_turns" in result.message


def test_parse_output_non_json_is_error():
    result = cr.parse_output("Traceback: boom", 1)
    assert result.status == cr.STATUS_ERROR


def test_parse_output_non_json_limit_text_is_limit():
    result = cr.parse_output("Claude AI usage limit reached|1761660000", 1)
    assert result.status == cr.STATUS_LIMIT


# ── claude_runner: körning med fake-runner ────────────────────────────────────

def test_run_claude_sends_prompt_on_stdin_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live-should-not-leak")
    seen = {}

    def fake_runner(command, **kwargs):
        seen.update(kwargs, command=command)
        return SimpleNamespace(stdout=_json(), returncode=0)

    result = cr.run_claude("analyst", "Lång prompt", cr.MODEL_ANALYST, tmp_path, runner=fake_runner)
    assert result.is_ok
    assert seen["input"] == "Lång prompt"
    assert "Lång prompt" not in seen["command"]
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert seen["cwd"] == str(tmp_path)


def test_run_claude_timeout_returns_error(tmp_path):
    def fake_runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    result = cr.run_claude("analyst", "x", cr.MODEL_ANALYST, tmp_path, timeout_s=1, runner=fake_runner)
    assert result.status == cr.STATUS_ERROR
    assert "Timeout" in result.message


def test_run_claude_missing_binary_returns_error(tmp_path):
    def fake_runner(command, **kwargs):
        raise FileNotFoundError("claude")

    result = cr.run_claude("analyst", "x", cr.MODEL_ANALYST, tmp_path, runner=fake_runner)
    assert result.status == cr.STATUS_ERROR


# ── run_state ─────────────────────────────────────────────────────────────────

@pytest.fixture
def run(tmp_path):
    protocol = tmp_path / "clio-research-099.md"
    protocol.write_text("# Protokoll", encoding="utf-8")
    state, run_dir = rs.create_run("clio-research-099_x", protocol, runs_dir=tmp_path / "runs")
    return state, run_dir


def test_create_run_copies_protocol_and_saves_state(run):
    state, run_dir = run
    assert (run_dir / "protocol.md").read_text(encoding="utf-8") == "# Protokoll"
    assert rs.load_state(run_dir).run_id == "clio-research-099_x"
    assert state.protocol_id == "clio-research-099"


def test_create_run_refuses_existing_dir(run, tmp_path):
    _, run_dir = run
    with pytest.raises(FileExistsError):
        rs.create_run(run_dir.name, run_dir / "protocol.md", runs_dir=run_dir.parent)


def test_set_status_validates(run):
    state, _ = run
    rs.set_status(state, "collecting", step="S1_collect")
    assert state.history[-1]["status"] == "collecting"
    with pytest.raises(ValueError):
        rs.set_status(state, "klar")
    with pytest.raises(ValueError):
        rs.set_status(state, "reviewing", step="S9")


def test_pause_and_resume_keeps_step(run):
    state, run_dir = run
    rs.set_status(state, "analysing", step="S2_analyse")
    rs.mark_paused(state, "limit")
    rs.save_state(state, run_dir)
    loaded = rs.load_state(run_dir)
    assert loaded.status == "paused_limit"
    assert rs.resume(loaded) == "S2_analyse"
    assert loaded.paused_step is None


def test_revision_rounds_are_capped(run):
    state, _ = run
    assert rs.can_revise(state)
    state.revision_round = rs.MAX_REVISION_ROUNDS
    assert not rs.can_revise(state)


def test_next_draft_never_overwrites(run):
    state, run_dir = run
    first = rs.next_draft(state, run_dir)
    assert first.name == "02_draft_v1.md"
    rs.draft_path(run_dir, 2).write_text("finns", encoding="utf-8")
    with pytest.raises(FileExistsError):
        rs.next_draft(state, run_dir)


def test_record_usage_sums_and_logs(run):
    state, run_dir = run
    usage = {"input_tokens": 2, "cache_read_input_tokens": 100, "output_tokens": 7}
    rs.record_usage(state, run_dir, "S2_analyse", cr.MODEL_ANALYST, usage, 0.5)
    rs.record_usage(state, run_dir, "S3b_review", cr.MODEL_REVIEWER, usage, 0.25)
    assert state.usage == {"input_tokens": 204, "output_tokens": 14, "cost_usd": 0.75}
    assert "S3b_review" in (run_dir / "run.log").read_text(encoding="utf-8")
