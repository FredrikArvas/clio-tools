"""
run_state.py
Tillstånd och körkatalog för research-pipeline v2 (S1 insamling → S4 leverans).

Varje körning får en egen katalog utanför git-repot, så att repots CLAUDE.md inte
laddas in i `claude -p`-sessionerna:

    <RUNS_DIR>/<run_id>/
        state.json            tillstånd (skrivs atomiskt)
        protocol.md           ifylld mall
        01_sources.md/.json   insamling
        02_draft_vN.md        utkast (alla versioner sparas)
        03_refcheck_vN.md     deterministisk referenskontroll
        03_review_vN.md       granskning
        final.md / final.docx
        run.log               steg, status och token-förbrukning

Environment:
    CLIO_RESEARCH_RUNS_DIR  – ersätter standardkatalogen ~/clio-research-runs
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "0.1.0"

RUNS_DIR = Path(os.environ.get("CLIO_RESEARCH_RUNS_DIR", Path.home() / "clio-research-runs"))
STATE_FILE = "state.json"
LOG_FILE   = "run.log"
MAX_REVISION_ROUNDS = 2

STEPS = ("S1_collect", "S2_analyse", "S3a_refcheck", "S3b_review", "S4_deliver")

STATUSES = (
    "inbox", "collecting", "analysing", "reviewing", "revising",
    "ready_for_human", "delivered", "needs_human", "paused_limit",
)

log = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class RunState:
    run_id: str
    protocol_id: str
    status: str = "inbox"
    current_step: str = STEPS[0]
    draft_version: int = 0
    revision_round: int = 0
    paused_step: str | None = None
    started: str = field(default_factory=lambda: _now())
    updated: str = field(default_factory=lambda: _now())
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    history: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Run directory ─────────────────────────────────────────────────────────────

def create_run(run_id: str, protocol_path: Path, runs_dir: Path = RUNS_DIR) -> tuple[RunState, Path]:
    """Skapa körkatalog, kopiera protokollet och spara första tillståndet."""
    run_dir = runs_dir / run_id
    if run_dir.exists():
        raise FileExistsError(f"Körkatalogen finns redan: {run_dir}")
    run_dir.mkdir(parents=True)
    shutil.copyfile(protocol_path, run_dir / "protocol.md")
    state = RunState(run_id=run_id, protocol_id=protocol_path.stem)
    save_state(state, run_dir)
    append_run_log(run_dir, f"skapad från {protocol_path.name}")
    return state, run_dir


def save_state(state: RunState, run_dir: Path) -> None:
    """Skriv state.json atomiskt (tempfil + replace)."""
    state.updated = _now()
    target = run_dir / STATE_FILE
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def load_state(run_dir: Path) -> RunState:
    data = json.loads((run_dir / STATE_FILE).read_text(encoding="utf-8"))
    return RunState(**data)


def append_run_log(run_dir: Path, line: str) -> None:
    with open(run_dir / LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(f"{_now()}  {line}\n")


# ── Transitions ───────────────────────────────────────────────────────────────

def set_status(state: RunState, status: str, step: str | None = None, note: str = "") -> None:
    """Byt status (och ev. steg). Ogiltiga värden kastar ValueError."""
    if status not in STATUSES:
        raise ValueError(f"Okänd status: {status!r}")
    if step is not None and step not in STEPS:
        raise ValueError(f"Okänt steg: {step!r}")
    if step is not None:
        state.current_step = step
    state.status = status
    state.history.append({"at": _now(), "status": status, "step": state.current_step, "note": note})


def mark_paused(state: RunState, message: str) -> None:
    """Prenumerationsgräns nådd: kom ihåg steget så att nästa körning fortsätter där."""
    state.paused_step = state.current_step
    set_status(state, "paused_limit", note=message)


def resume(state: RunState) -> str:
    """Återuppta efter paus. Returnerar steget som ska köras."""
    step = state.paused_step or state.current_step
    state.paused_step = None
    state.history.append({"at": _now(), "status": "resumed", "step": step, "note": ""})
    return step


def can_revise(state: RunState) -> bool:
    return state.revision_round < MAX_REVISION_ROUNDS


def record_usage(state: RunState, run_dir: Path, step: str, model: str, usage: dict, cost_usd: float) -> None:
    """Summera token-förbrukning i state och logga per steg i run.log."""
    input_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0)) \
        + int(usage.get("cache_read_input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    state.usage["input_tokens"] += input_tokens
    state.usage["output_tokens"] += output_tokens
    state.usage["cost_usd"] = round(state.usage["cost_usd"] + cost_usd, 4)
    append_run_log(run_dir, f"{step}  {model}  in={input_tokens}  out={output_tokens}  "
                            f"ref_usd={cost_usd:.4f}")


# ── Versioned artefacts ───────────────────────────────────────────────────────

def draft_path(run_dir: Path, version: int) -> Path:
    return run_dir / f"02_draft_v{version}.md"


def refcheck_path(run_dir: Path, version: int) -> Path:
    return run_dir / f"03_refcheck_v{version}.md"


def review_path(run_dir: Path, version: int) -> Path:
    return run_dir / f"03_review_v{version}.md"


def next_draft(state: RunState, run_dir: Path) -> Path:
    """Räkna upp utkastversionen. Befintliga filer skrivs aldrig över."""
    state.draft_version += 1
    path = draft_path(run_dir, state.draft_version)
    if path.exists():
        raise FileExistsError(f"Utkastet finns redan: {path}")
    return path
