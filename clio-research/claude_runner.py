"""
claude_runner.py
Kör ett LLM-steg i research-pipelinen via `claude -p` (Claude Code headless).
Anropet går alltid på prenumerationen: API-nycklar tas bort ur barnprocessens miljö.

Usage:
    from claude_runner import run_claude, MODEL_ANALYST
    result = run_claude("analyst", prompt, MODEL_ANALYST, run_dir, system_prompt=...)

Säkerhetsmodell:
    - Ingen roll har både filläsning och nätverk. Allt underlag skickas i prompten
      (via stdin), och Python skriver alla filer. Modellen skriver aldrig själv.
    - --setting-sources project: serverns globala CLAUDE.md (skämt, token-räkning)
      laddas inte. Körkatalogen ska ligga utanför git-repot (se run_state.RUNS_DIR).
    - --strict-mcp-config: inga MCP-servrar från användarens konfiguration.

Environment:
    ANTHROPIC_API_KEY  – tas BORT före anropet (annars debiteras API:t)
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "0.1.0"

CLAUDE_BINARY     = "claude"
MODEL_COLLECTOR   = "claude-sonnet-4-6"
MODEL_ANALYST     = "claude-opus-5-5"
MODEL_REVIEWER    = MODEL_ANALYST
DEFAULT_TIMEOUT_S = 3600

STRIPPED_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

ROLE_TOOLS = {
    "collector": ("WebSearch", "WebFetch"),
    "analyst":   (),
    "reviewer":  ("WebFetch",),
}

LIMIT_PATTERN = re.compile(
    r"usage limit|hit your limit|limit reached|rate.?limit|overloaded|resets? (at|in)",
    re.IGNORECASE,
)

STATUS_OK    = "ok"
STATUS_LIMIT = "limit"
STATUS_ERROR = "error"

log = logging.getLogger(__name__)


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class ClaudeResult:
    status: str
    text: str = ""
    message: str = ""
    session_id: str | None = None
    model: str = ""
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0

    @property
    def is_ok(self) -> bool:
        return self.status == STATUS_OK


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_env(base: dict | None = None) -> dict:
    """Kopia av miljön utan API-nycklar, så att CLI:t använder prenumerationen."""
    env = dict(os.environ if base is None else base)
    for key in STRIPPED_ENV_VARS:
        env.pop(key, None)
    return env


def build_command(role: str, model: str, system_prompt: str | None = None,
                  max_turns: int | None = None) -> list[str]:
    """Bygg argv för `claude -p`. Prompten skickas via stdin, inte som argument."""
    if role not in ROLE_TOOLS:
        raise ValueError(f"Okänd roll: {role!r}")
    tools = ",".join(ROLE_TOOLS[role])
    command = [
        CLAUDE_BINARY, "-p",
        "--model", model,
        "--output-format", "json",
        "--tools", tools,
        "--setting-sources", "project",
        "--strict-mcp-config",
        "--no-session-persistence",
    ]
    if tools:
        command += ["--allowedTools", tools]
    if system_prompt:
        command += ["--system-prompt", system_prompt]
    if max_turns:
        command += ["--max-turns", str(max_turns)]
    return command


def parse_output(stdout: str, returncode: int, model: str = "") -> ClaudeResult:
    """Tolka JSON-svaret från `claude -p --output-format json`."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        snippet = (stdout or "").strip()[:300]
        status = STATUS_LIMIT if LIMIT_PATTERN.search(snippet) else STATUS_ERROR
        return ClaudeResult(status, message=f"Ej JSON (exit {returncode}): {snippet}", model=model)

    text = data.get("result") or ""
    result = ClaudeResult(
        status=STATUS_OK,
        text=text,
        session_id=data.get("session_id"),
        model=model,
        usage=data.get("usage") or {},
        cost_usd=float(data.get("total_cost_usd") or 0.0),
    )
    if data.get("is_error") or returncode != 0:
        result.status = STATUS_LIMIT if LIMIT_PATTERN.search(text) else STATUS_ERROR
        result.message = f"{data.get('subtype', 'error')}: {text[:300]}"
    return result


# ── Main entry ────────────────────────────────────────────────────────────────

def run_claude(role: str, prompt: str, model: str, workdir: Path,
               system_prompt: str | None = None, max_turns: int | None = None,
               timeout_s: int = DEFAULT_TIMEOUT_S,
               runner: Callable = subprocess.run) -> ClaudeResult:
    """Kör ett steg. Returnerar alltid ett ClaudeResult, kastar aldrig vid körfel."""
    command = build_command(role, model, system_prompt, max_turns)
    log.info("claude -p  roll=%s  modell=%s  prompt=%d tecken", role, model, len(prompt))
    try:
        completed = runner(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(workdir),
            env=build_env(),
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        log.error("claude -p avbröts efter %d s (roll=%s)", timeout_s, role)
        return ClaudeResult(STATUS_ERROR, message=f"Timeout efter {timeout_s} s", model=model)
    except FileNotFoundError:
        log.error("Hittar inte %s i PATH", CLAUDE_BINARY)
        return ClaudeResult(STATUS_ERROR, message=f"{CLAUDE_BINARY} saknas i PATH", model=model)

    result = parse_output(completed.stdout, completed.returncode, model)
    if not result.is_ok:
        log.warning("claude -p %s: %s", result.status, result.message)
    return result
