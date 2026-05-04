"""
main.py — clio-research entry point.

Användning:
  python main.py --protocol clio-research-001
  python main.py --list
  python main.py --status clio-research-001_20260503_142300
  python main.py --resume clio-research-001_20260503_142300
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent

load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=True)

sys.path.insert(0, str(BASE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("clio-research")

INBOX_DIR = BASE_DIR / "inbox"
RUNNING_DIR = BASE_DIR / "running"
DONE_DIR = BASE_DIR / "done"

for d in (INBOX_DIR, RUNNING_DIR, DONE_DIR):
    d.mkdir(exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="clio-research — multi-lingual evidence pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--protocol", metavar="ID", help="Kör protokoll från inbox/[ID].json")
    group.add_argument("--list", action="store_true", help="Lista protokoll (inbox, running, done)")
    group.add_argument("--status", metavar="RUN_ID", help="Visa status för körning")
    group.add_argument("--resume", metavar="RUN_ID", help="Återuppta avbruten körning")

    args = parser.parse_args()

    if args.list:
        _cmd_list()
    elif args.status:
        _cmd_status(args.status)
    elif args.protocol:
        _cmd_run(args.protocol, resume_run_id=None)
    elif args.resume:
        run_id = args.resume
        state = _load_state(run_id)
        if not state:
            print(f"State-fil saknas för: {run_id}")
            sys.exit(1)
        _cmd_run(state["protocol_id"], resume_run_id=run_id)


def _cmd_list() -> None:
    print("\n=== clio-research — Protokolloversikt ===\n")

    print("INBOX:")
    for f in sorted(INBOX_DIR.glob("*.json")):
        print(f"  {f.stem}")

    print("\nRUNNING:")
    for f in sorted(RUNNING_DIR.glob("*.json")):
        state = json.loads(f.read_text(encoding="utf-8"))
        phase = state.get("last_completed_phase", 0)
        print(f"  {f.stem}  (fas {phase}/8 klar)")

    print("\nDONE:")
    for f in sorted(DONE_DIR.glob("*.md")):
        print(f"  {f.stem}")
    print()


def _cmd_status(run_id: str) -> None:
    state = _load_state(run_id)
    if not state:
        state_path = RUNNING_DIR / f"{run_id}.json"
        done_path = DONE_DIR / f"{run_id}.md"
        if done_path.exists():
            print(f"{run_id}: KLAR (rapport: {done_path})")
        else:
            print(f"Ingen state-fil för: {run_id}")
        return

    print(f"\nKörning: {run_id}")
    print(f"Protokoll: {state.get('protocol_id')}")
    print(f"Startad: {state.get('started')}")
    print(f"Senaste fas: {state.get('last_completed_phase', 0)}/8")
    print(f"Källor insamlade: {state.get('sources_collected', 0)}")
    print(f"Fel: {len(state.get('errors', []))}")


def _cmd_run(protocol_id: str, resume_run_id: str | None) -> None:
    import protocol_loader
    import search_runner
    import citation_chaser
    import credibility_scorer
    import report_builder
    import status_mailer
    import qdrant_indexer

    protocol = protocol_loader.load(protocol_id, INBOX_DIR)
    run_id = resume_run_id or protocol["run_id"]

    if resume_run_id:
        state = _load_state(resume_run_id)
        sources = state.get("sources", [])
        seen_ids = set(s["source_id"] for s in sources if s.get("source_id"))
        start_phase = state.get("last_completed_phase", 0) + 1
        logger.info("Återupptar körning %s från fas %d", run_id, start_phase)
    else:
        sources = []
        seen_ids = set()
        start_phase = 1
        logger.info("Startar ny körning: %s", run_id)

    state = _init_state(run_id, protocol_id)
    _save_state(state, sources)

    phases = protocol["search_strategy"]["phases"]

    for phase_def in phases:
        phase_num = phase_def["phase"]
        if phase_num < start_phase:
            continue

        label = phase_def.get("label", f"Fas {phase_num}")

        if phase_num <= 4:
            logger.info("=== Fas %d: %s ===", phase_num, label)
            new = search_runner.run_phase(phase_def, protocol, seen_ids)
            sources.extend(new)

            if len(new) == 0:
                msg = f"Fas {phase_num} ({label}): Noll resultat"
                logger.warning(msg)
                status_mailer.send_anomaly(run_id, phase_num, msg)

        elif phase_num == 5:
            logger.info("=== Fas 5: Citation chase ===")
            credibility_scorer.score_all(sources)
            new = citation_chaser.chase(sources, seen_ids, depth=1)
            sources.extend(new)

        elif phase_num == 6:
            logger.info("=== Fas 6: Credibility scoring ===")
            credibility_scorer.score_all(sources)

        elif phase_num == 7:
            logger.info("=== Fas 7: Rapport building ===")
            credibility_scorer.score_all(sources)
            report_path = report_builder.build(protocol, sources, run_id, DONE_DIR)
            state["report_path"] = str(report_path)

        elif phase_num == 8:
            logger.info("=== Fas 8: Delivery ===")
            rp = Path(state.get("report_path", ""))
            if rp.exists():
                qdrant_indexer.index_report(protocol, sources, rp, run_id)
                status_mailer.send_final_report(run_id, rp)
            else:
                logger.warning("Rapport saknas för delivery-fas")

        state["last_completed_phase"] = phase_num
        state["sources_collected"] = len(sources)
        _save_state(state, sources)

        if protocol["output"].get("status_updates") and phase_num <= 4:
            status_mailer.send_phase_complete(
                run_id, phase_num, label,
                source_count=len(sources),
                relevant_count=len([s for s in sources if s.get("phase_found") == phase_num]),
            )

    _move_to_done(run_id)
    logger.info("Körning %s klar. Källor: %d", run_id, len(sources))


def _init_state(run_id: str, protocol_id: str) -> dict:
    return {
        "run_id": run_id,
        "protocol_id": protocol_id,
        "started": datetime.now().isoformat(),
        "last_completed_phase": 0,
        "sources_collected": 0,
        "sources_by_phase": {},
        "errors": [],
        "report_path": None,
    }


def _save_state(state: dict, sources: list[dict]) -> None:
    state_data = {**state, "sources": sources}
    path = RUNNING_DIR / f"{state['run_id']}.json"
    path.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_state(run_id: str) -> dict | None:
    path = RUNNING_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _move_to_done(run_id: str) -> None:
    src = RUNNING_DIR / f"{run_id}.json"
    if src.exists():
        dst = DONE_DIR / f"{run_id}.state.json"
        src.rename(dst)


if __name__ == "__main__":
    main()
