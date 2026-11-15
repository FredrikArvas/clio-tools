"""
main.py — clio-research, orkestrerare för research-pipeline v2.

Användning (från clio-tools-roten):
  python3 clio-research/main.py --protocol clio-research-021 [--niva snabb]
  python3 clio-research/main.py --list
  python3 clio-research/main.py --status clio-research-021_20261115_142300
  python3 clio-research/main.py --resume clio-research-021_20261115_142300 [--force]

  Det äldre åttafasflödet (R1.x) finns kvar tills v2 är provat:
  python3 clio-research/main.py --legacy --protocol clio-research-021

Flödet (PLAN_research_pipeline_v2.md avsnitt 4):
  S1_collect    collector.collect            → 01_sources.json/.md, 01_filtered.json, kallor/
  S2_analyse    report_writer.analyse/revise → 02_draft_v<k>.md, 02_claims_v<k>.json
                + report_lint (report_writer.check) → 03_lint_v<k>.md
                MÅSTE-fel → revision, högst max_revisions varv (2), därefter needs_human
  S3a_refcheck  PLATS FÖR ref_checker.py (inte byggd)
  S3b_review    PLATS FÖR granskaren i ny session och motbevisvarvet på nivå delbar (inte byggda)
  S4_deliver    PLATS FÖR leveransen: Word, mail, Qdrant (inte byggd)
  → ready_for_human

Körkatalog: run_state (~/clio-research-runs/<run_id>/, utanför repot; CLIO_RESEARCH_RUNS_DIR).
Prenumerationsgräns (ClaudeResult.status == "limit") → paused_limit; --resume fortsätter
från samma steg. Tokens och modell per anrop skrivs i run.log. Alla modellanrop går via
claude_runner (prenumerationen, API-nyckeln tas bort ur barnprocessens miljö).

Slutkoder: 0 ready_for_human, 2 protokollfel, 3 paused_limit, 4 needs_human.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent

sys.path.insert(0, str(BASE_DIR))

import run_state as rs  # noqa: E402
from contact import redact  # noqa: E402

logger = logging.getLogger("clio-research")

INBOX_DIR = BASE_DIR / "inbox"
RUNNING_DIR = BASE_DIR / "running"          # bara det äldre flödet
DONE_DIR = BASE_DIR / "done"                # bara det äldre flödet

PROTOCOL_JSON = "protocol.json"
EXIT_OK, EXIT_PROTOCOL, EXIT_PAUSED, EXIT_HUMAN = 0, 2, 3, 4
STOP_STATUSES = ("paused_limit", "needs_human", "ready_for_human", "delivered")


# ── Inställningar ─────────────────────────────────────────────────────────────

def runs_dir() -> Path:
    """Läses vid anrop, så att CLIO_RESEARCH_RUNS_DIR kan sättas efter import (tester)."""
    return Path(os.environ.get("CLIO_RESEARCH_RUNS_DIR", rs.RUNS_DIR))


def _log(run_dir: Path, line: str) -> None:
    """Rad i run.log, med kontaktadressen bortmaskad."""
    rs.append_run_log(run_dir, redact(line))


@dataclass
class Steps:
    """Funktionerna flödet anropar. Byts ut i testerna."""
    runner: Callable
    collect: Callable
    analyse: Callable
    revise: Callable
    check: Callable


def default_steps() -> Steps:
    import collector
    import report_writer
    from claude_runner import run_claude
    return Steps(runner=run_claude, collect=collector.collect, analyse=report_writer.analyse,
                 revise=report_writer.revise, check=report_writer.check)


# ── Start och återupptag ──────────────────────────────────────────────────────

def start_run(protocol_ref: str, inbox_dir: Path | None = None, base: Path | None = None,
              niva: str | None = None, now: datetime | None = None) -> tuple[rs.RunState, Path, dict]:
    """Läs protokollet, skapa körkatalogen och spara det normaliserade protokollet.

    Raises:
        protocol_parser.ProtocolError: ofullständigt protokoll.
        FileNotFoundError: protokollfilen saknas.
    """
    import protocol_parser as pp
    path = pp.find_protocol(protocol_ref, inbox_dir or INBOX_DIR)
    protocol = pp.load_protocol(path)
    if niva:
        if niva not in pp.LEVELS:
            raise pp.ProtocolError([f"nivå {niva!r} är inte en av {', '.join(pp.LEVELS)}"], path)
        protocol["niva"] = niva
    run_id = f"{protocol['protocol_id']}_{(now or datetime.now()).strftime('%Y%m%d_%H%M%S')}"
    state, run_dir = rs.create_run(run_id, path, base or runs_dir())
    state.protocol_id = protocol["protocol_id"]
    (run_dir / PROTOCOL_JSON).write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    _log(run_dir, f"protokoll {path.name} ({protocol['format']}), nivå {protocol['niva']}, "
                  f"spridning {protocol['spridning']}")
    rs.save_state(state, run_dir)
    return state, run_dir, protocol


def open_run(run_id: str, base: Path | None = None) -> tuple[rs.RunState, Path, dict]:
    run_dir = (base or runs_dir()) / run_id
    if not (run_dir / rs.STATE_FILE).exists():
        raise FileNotFoundError(f"Ingen körning {run_id} i {run_dir.parent}")
    protocol = json.loads((run_dir / PROTOCOL_JSON).read_text(encoding="utf-8"))
    return rs.load_state(run_dir), run_dir, protocol


def prepare_resume(state: rs.RunState, run_dir: Path, force: bool = False) -> bool:
    """Gör tillståndet redo att köras vidare. False om det inte finns något att göra."""
    if state.status == "paused_limit":
        state.current_step = rs.resume(state)
        _log(run_dir, f"återupptas från {state.current_step}")
        return True
    if state.status in ("ready_for_human", "delivered"):
        return False
    if state.status == "needs_human":
        if not force:
            return False
        state.history.append({"at": rs._now(), "status": "resumed", "step": state.current_step,
                              "note": "--force efter needs_human"})
        _log(run_dir, f"återupptas med --force från {state.current_step}")
        return True
    _log(run_dir, f"återupptas efter avbrott i {state.current_step} (status {state.status})")
    return True


# ── Flödet ────────────────────────────────────────────────────────────────────

def _record(state: rs.RunState, run_dir: Path, label: str, result) -> None:
    if result is None:
        return
    rs.record_usage(state, run_dir, label, result.model or "?", result.usage or {}, result.cost_usd or 0.0)


def _stop(state: rs.RunState, run_dir: Path, status: str, note: str) -> rs.RunState:
    if status == "paused_limit":
        rs.mark_paused(state, redact(note))
    else:
        rs.set_status(state, status, note=redact(note))
    _log(run_dir, f"{state.current_step}: {status} – {note}")
    rs.save_state(state, run_dir)
    return state


def _lint_file(run_dir: Path, version: int) -> Path:
    return run_dir / f"03_lint_v{version}.json"


def run_pipeline(state: rs.RunState, run_dir: Path, protocol: dict, steps: Steps | None = None) -> rs.RunState:
    """Kör från state.current_step tills körningen är klar, pausad eller behöver en människa."""
    steps = steps or default_steps()
    level = protocol.get("niva", "standard")
    max_rounds = min(int(protocol.get("max_revisions", rs.MAX_REVISION_ROUNDS)), rs.MAX_REVISION_ROUNDS)

    while True:
        step = state.current_step

        if step == "S1_collect":
            rs.set_status(state, "collecting", step)
            rs.save_state(state, run_dir)
            _log(run_dir, f"S1_collect start (nivå {level})")
            res = steps.collect(run_dir, protocol, runner=steps.runner)
            for label, call in res.calls:
                _record(state, run_dir, label, call)
            if res.status == "limit":
                return _stop(state, run_dir, "paused_limit", res.message)
            if not res.is_ok:
                return _stop(state, run_dir, "needs_human", f"insamlingen misslyckades: {res.message}")
            _log(run_dir, f"S1_collect klar: {res.message}")
            if not res.counts.get("sources"):
                return _stop(state, run_dir, "needs_human", "inga källor i underlaget efter insamlingen")
            state.current_step = "S2_analyse"
            rs.save_state(state, run_dir)

        elif step == "S2_analyse":
            revising = state.draft_version > 0
            rs.set_status(state, "revising" if revising else "analysing", step)
            rs.save_state(state, run_dir)
            if revising:
                lint_data = json.loads(_lint_file(run_dir, state.draft_version).read_text(encoding="utf-8"))
                _log(run_dir, f"S2 revision {state.revision_round} av utkast v{state.draft_version} "
                              f"({len(lint_data['requirements'])} krav)")
                draft = steps.revise(run_dir, protocol, lint_data["requirements"],
                                     previous=state.draft_version, runner=steps.runner)
            else:
                _log(run_dir, "S2 första utkast")
                draft = steps.analyse(run_dir, protocol, runner=steps.runner, version=1)
            _record(state, run_dir, f"S2_analyse/v{draft.version}", draft.result)
            result = draft.result
            if result is not None and result.status == "limit":
                return _stop(state, run_dir, "paused_limit", f"prenumerationsgräns i S2: {result.message}")
            if result is not None and result.status == "error":
                return _stop(state, run_dir, "needs_human", f"analysanropet misslyckades: {result.message}")

            lint = steps.check(run_dir, protocol, draft)
            payload = {"version": draft.version, "status": lint.status, "must": len(lint.must),
                       "should": len(lint.should), "requirements": lint.requirements()}
            _lint_file(run_dir, draft.version).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                                          encoding="utf-8")
            state.draft_version = draft.version
            _log(run_dir, f"rapportkontroll v{draft.version}: {lint.status}, MÅSTE {len(lint.must)}, "
                          f"BÖR {len(lint.should)}")
            if lint.status == "PASS":
                state.current_step = "S3a_refcheck"
                rs.save_state(state, run_dir)
            elif state.revision_round < max_rounds:
                state.revision_round += 1
                rs.save_state(state, run_dir)
            else:
                return _stop(state, run_dir, "needs_human",
                             f"MÅSTE-fel kvar i utkast v{draft.version} efter {state.revision_round} revisionsvarv")

        elif step == "S3a_refcheck":
            # PLATS FÖR ref_checker.py: [n] ↔ litteraturlista ↔ 01_sources.json, DOI mot CrossRef,
            # URL 200/3xx (403 noteras). MÅSTE-fel ska leda tillbaka till S2 som en revision.
            rs.set_status(state, "reviewing", step)
            _log(run_dir, "S3a_refcheck: ref_checker.py inte byggd – steget hoppas över")
            state.current_step = "S3b_review"
            rs.save_state(state, run_dir)

        elif step == "S3b_review":
            # PLATS FÖR granskaren (Opus, ny session, roll reviewer) på standard och delbar,
            # och motbevisvarvet (B15) på delbar. REVISE → S2, FAIL → needs_human.
            note = "ingen granskning på nivå snabb" if level == "snabb" else "granskaren inte byggd – steget hoppas över"
            _log(run_dir, f"S3b_review: {note}")
            state.current_step = "S4_deliver"
            rs.save_state(state, run_dir)

        elif step == "S4_deliver":
            # PLATS FÖR leveransen: final.md, Word (report_writer.build_word), Dropbox, mail och Qdrant.
            final = rs.draft_path(run_dir, state.draft_version)
            if final.exists():
                (run_dir / "final.md").write_text(final.read_text(encoding="utf-8"), encoding="utf-8")
            _log(run_dir, "S4_deliver: leverans inte byggd – final.md kopierad, ingen Word, mail eller Qdrant")
            return _stop(state, run_dir, "ready_for_human",
                         f"utkast v{state.draft_version} godkänt av rapportkontrollen; granskning och leverans återstår")

        else:
            return _stop(state, run_dir, "needs_human", f"okänt steg {step!r}")


def exit_code(state: rs.RunState) -> int:
    return {"ready_for_human": EXIT_OK, "delivered": EXIT_OK, "paused_limit": EXIT_PAUSED}.get(state.status, EXIT_HUMAN)


# ── Kommandon (v2) ────────────────────────────────────────────────────────────

def cmd_run(protocol_ref: str, niva: str | None = None, steps: Steps | None = None) -> int:
    import protocol_parser as pp
    try:
        state, run_dir, protocol = start_run(protocol_ref, niva=niva)
    except (pp.ProtocolError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_PROTOCOL
    print(f"Körning {state.run_id} i {run_dir}")
    state = run_pipeline(state, run_dir, protocol, steps)
    _print_state(state)
    return exit_code(state)


def cmd_resume(run_id: str, force: bool = False, steps: Steps | None = None) -> int:
    state, run_dir, protocol = open_run(run_id)
    if not prepare_resume(state, run_dir, force):
        print(f"{run_id}: status {state.status}, inget att återuppta"
              + (" (använd --force)" if state.status == "needs_human" else ""))
        return exit_code(state)
    state = run_pipeline(state, run_dir, protocol, steps)
    _print_state(state)
    return exit_code(state)


def cmd_list() -> None:
    print("\n=== clio-research v2 ===\n\nINBOX:")
    for f in sorted(list(INBOX_DIR.glob("*.md")) + list(INBOX_DIR.glob("*.json"))):
        print(f"  {f.name}")
    print(f"\nKÖRNINGAR ({runs_dir()}):")
    base = runs_dir()
    for d in sorted(base.glob("*/" + rs.STATE_FILE)) if base.exists() else []:
        st = rs.load_state(d.parent)
        print(f"  {st.run_id}  {st.status}  ({st.current_step}, utkast v{st.draft_version})")
    print()


def cmd_status(run_id: str) -> int:
    try:
        state, run_dir, _ = open_run(run_id)
    except FileNotFoundError as exc:
        print(exc)
        return EXIT_HUMAN
    _print_state(state)
    print(f"Katalog: {run_dir}")
    return EXIT_OK


def _print_state(state: rs.RunState) -> None:
    last = state.history[-1]["note"] if state.history else ""
    print(f"{state.run_id}: {state.status} (steg {state.current_step}, utkast v{state.draft_version}, "
          f"revisionsvarv {state.revision_round})")
    if last:
        print(f"  {last}")
    print(f"  tokens in={state.usage['input_tokens']} out={state.usage['output_tokens']}")


# ── Det äldre åttafasflödet (R1.x), bakom --legacy ────────────────────────────

def _legacy_list() -> None:
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


def _legacy_status(run_id: str) -> None:
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


def _legacy_run(protocol_id: str, resume_run_id: str | None) -> None:
    import protocol_loader
    import search_runner
    import citation_chaser
    import credibility_scorer
    import relevance_filter
    import report_builder
    import status_mailer
    import qdrant_indexer

    protocol = protocol_loader.load(protocol_id, INBOX_DIR)
    run_id = resume_run_id or protocol["run_id"]
    question = protocol["question"]["natural_language"]

    if resume_run_id:
        state = _load_state(resume_run_id)
        sources = state.get("sources", [])
        seen_ids = set(s["source_id"] for s in sources if s.get("source_id"))
        start_phase = state.get("last_completed_phase", 0) + 1
        logger.info("Återupptar körning %s från fas %d", run_id, start_phase)
    else:
        # Ladda cachade källor från tidigare körningar
        cached = qdrant_indexer.load_cached_sources(question)
        sources = cached
        seen_ids = set(s["source_id"] for s in cached if s.get("source_id"))
        if cached:
            logger.info("Laddade %d cachade källor från Qdrant", len(cached))
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
                question = protocol["question"].get("natural_language", "")
                status_mailer.send_anomaly(run_id, phase_num, msg, question=question)

        elif phase_num == 5:
            logger.info("=== Fas 5: Citation chase ===")
            credibility_scorer.score_all(sources)
            new = citation_chaser.chase(sources, seen_ids, depth=1)
            sources.extend(new)

        elif phase_num == 6:
            logger.info("=== Fas 6: Credibility scoring ===")
            credibility_scorer.score_all(sources)
            logger.info("=== Fas 6.5: Relevansfiltrering ===")
            relevant_sources = relevance_filter.filter_by_relevance(sources, question)
            state["relevant_sources_count"] = len(relevant_sources)
            if not relevant_sources:
                status_mailer.send_anomaly(
                    run_id, 6,
                    f"Relevansfilter returnerade 0 av {len(sources)} källor. "
                    f"Kontrollera söktermer i protokollet.",
                    question=question,
                )

        elif phase_num == 7:
            logger.info("=== Fas 7: Rapport building ===")
            report_path = report_builder.build(protocol, relevant_sources, run_id, DONE_DIR)
            state["report_path"] = str(report_path)

        elif phase_num == 8:
            logger.info("=== Fas 8: Delivery ===")
            rp = Path(state.get("report_path", ""))
            if rp.exists():
                qdrant_indexer.index_report(protocol, relevant_sources, rp, run_id)
                status_mailer.send_final_report(run_id, rp, question=question)
            else:
                logger.warning("Rapport saknas för delivery-fas")

        state["last_completed_phase"] = phase_num
        state["sources_collected"] = len(sources)
        _save_state(state, sources)

        if protocol["output"].get("status_updates") and phase_num <= 4:
            question = protocol["question"].get("natural_language", "")
            status_mailer.send_phase_complete(
                run_id, phase_num, label,
                source_count=len(sources),
                relevant_count=len([s for s in sources if s.get("phase_found") == phase_num]),
                question=question,
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



# ── Ingång ────────────────────────────────────────────────────────────────────

def _setup() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env", override=True)
    load_dotenv(BASE_DIR / ".env", override=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="clio-research — evidenspipeline v2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--protocol", metavar="ID", help="Kör protokoll från inbox/ (ID.md före ID.json)")
    group.add_argument("--list", action="store_true", help="Lista protokoll och körningar")
    group.add_argument("--status", metavar="RUN_ID", help="Visa status för körning")
    group.add_argument("--resume", metavar="RUN_ID", help="Återuppta pausad eller avbruten körning")
    parser.add_argument("--niva", choices=("snabb", "standard", "delbar"), help="Skriver över protokollets nivå")
    parser.add_argument("--force", action="store_true", help="--resume även efter needs_human")
    parser.add_argument("--legacy", action="store_true", help="Det äldre åttafasflödet (R1.x, bara JSON)")
    args = parser.parse_args(argv)
    _setup()

    if args.legacy:
        for d in (INBOX_DIR, RUNNING_DIR, DONE_DIR):
            d.mkdir(exist_ok=True)
        if args.list:
            _legacy_list()
        elif args.status:
            _legacy_status(args.status)
        elif args.protocol:
            _legacy_run(args.protocol, resume_run_id=None)
        elif args.resume:
            state = _load_state(args.resume)
            if not state:
                print(f"State-fil saknas för: {args.resume}")
                return 1
            _legacy_run(state["protocol_id"], resume_run_id=args.resume)
        return 0

    if args.list:
        cmd_list()
        return 0
    if args.status:
        return cmd_status(args.status)
    if args.resume:
        return cmd_resume(args.resume, force=args.force)
    return cmd_run(args.protocol, niva=args.niva)


if __name__ == "__main__":
    sys.exit(main())
