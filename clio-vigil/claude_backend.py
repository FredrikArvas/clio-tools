"""
clio-vigil — claude_backend.py
==============================
Claude via prenumerationen (`claude -p`) på servern, delad av summarizern
och UAP-klassificeraren.

Anropen går genom clio-research/claude_runner.py, som tar bort
ANTHROPIC_API_KEY ur miljön så att API:t inte debiteras.

Fälla: serverns globala ~/.claude/CLAUDE.md (tokenfot, skämt) laddas trots
--setting-sources project. Systemprompten får därför OUTPUT_ONLY_INSTRUCTION
och svaret klipps med strip_cli_extras.
"""

import importlib.util
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

RUNNER_PATH = Path(__file__).resolve().parent.parent / "clio-research" / "claude_runner.py"
CLAUDE_WORKDIR = Path(os.getenv("VIGIL_CLAUDE_WORKDIR",
                                str(Path.home() / ".cache" / "clio-vigil-claude")))
CLAUDE_TIMEOUT_SECONDS = 300
RUNNER_ROLE = "analyst"   # roll utan verktyg i claude_runner

OUTPUT_ONLY_INSTRUCTION = (
    "Svara ENBART med det efterfrågade svaret. Inga tokenestimat, inga skämt, "
    "ingen inledning eller avslutning."
)
CLI_FOOTER_PATTERN = re.compile(r"^\s*(📊|🎪|---\s*$)")


class SubscriptionLimitError(RuntimeError):
    """Prenumerationens kvot är nådd. Gäller resten av processens körning."""


_runner = None
_is_limited = False


def is_limited() -> bool:
    return _is_limited


def load_runner():
    """Laddar claude_runner från clio-research (cachas)."""
    global _runner
    if _runner is None:
        spec = importlib.util.spec_from_file_location("claude_runner", RUNNER_PATH)
        module = importlib.util.module_from_spec(spec)
        # Dataclasses i modulen slår upp sys.modules[__module__] — registrera först.
        sys.modules["claude_runner"] = module
        spec.loader.exec_module(module)
        _runner = module
    return _runner


def strip_cli_extras(text: str) -> str:
    """Klipper vid första raden med tokenfot, skämt eller '---'."""
    lines = (text or "").strip().splitlines()
    for idx, line in enumerate(lines):
        if CLI_FOOTER_PATTERN.match(line):
            lines = lines[:idx]
            break
    return "\n".join(lines).strip()


def call_subscription(system_prompt: str, user_message: str, model: str) -> str:
    """
    Kör en fråga via `claude -p` och returnerar den rensade svarstexten.

    Kastar SubscriptionLimitError vid kvotgräns (och för alla senare anrop i
    samma process), RuntimeError vid andra fel eller tomt svar.
    """
    global _is_limited
    if _is_limited:
        raise SubscriptionLimitError("Prenumerationens kvot nådd tidigare i körningen")

    runner = load_runner()
    CLAUDE_WORKDIR.mkdir(parents=True, exist_ok=True)
    result = runner.run_claude(
        RUNNER_ROLE, user_message, model, CLAUDE_WORKDIR,
        system_prompt=f"{system_prompt}\n\n{OUTPUT_ONLY_INSTRUCTION}",
        max_turns=1, timeout_s=CLAUDE_TIMEOUT_SECONDS,
    )
    if result.status == runner.STATUS_LIMIT:
        _is_limited = True
        logger.warning("claude -p: kvotgräns nådd — inga fler Claude-anrop i den här körningen")
        raise SubscriptionLimitError(result.message)
    if not result.is_ok:
        raise RuntimeError(f"claude -p {result.status}: {result.message}")
    text = strip_cli_extras(result.text)
    if not text:
        raise RuntimeError("claude -p gav tomt svar")
    return text
