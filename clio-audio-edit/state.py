"""
state.py — Delat tillstånd för clio-audio-edit.
Läser/skriver till den gemensamma clio_state.json.
"""

import json
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / "config" / "clio_state.json"
MODULE_NAME = "clio-audio-edit"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_folder": {}, "runs": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def save_last_folder(folder: str) -> None:
    state = load_state()
    state.setdefault("last_folder", {})[MODULE_NAME] = folder
    folders = state.setdefault("recent_folders", [])
    if folder in folders:
        folders.remove(folder)
    folders.append(folder)
    state["recent_folders"] = folders[-10:]
    save_state(state)
