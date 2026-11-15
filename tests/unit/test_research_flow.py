"""
test_research_flow.py — Flödet i main.py: S1 → S2 → rapportkontroll → revision, paus och
återupptagning.

S1 är simulerat (skriver spår 2:s provunderlag). S2 och rapportkontrollen är de riktiga
report_writer- och report_lint-funktionerna, med en låtsaslöpare i stället för modellen.
Inga nät- eller modellanrop. Körs en fil i taget: `python -m pytest tests/unit/test_research_flow.py`.
"""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "clio-research"))
sys.path.insert(0, str(HERE))

import collector  # noqa: E402
import main  # noqa: E402
import report_writer as rw  # noqa: E402
import run_state as rs  # noqa: E402
import source_model as sm  # noqa: E402
import test_research_writer as tw  # noqa: E402
from claude_runner import MODEL_ANALYST, MODEL_COLLECTOR, ClaudeResult  # noqa: E402

GOOD = tw.response()
BAD = tw.response(end=False)            # avklippt svar → MÅSTE
SECRET = "hemlig.adress@example.org"


class Runner:
    """Analytikerns svar i tur och ordning. Svaret "LIMIT" ger prenumerationsgräns."""

    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = []

    def __call__(self, role, prompt, model, workdir, system_prompt=None, **kw):
        self.calls.append({"role": role, "model": model, "prompt": prompt})
        text = self.texts.pop(0)
        if text == "LIMIT":
            return ClaudeResult("limit", message="You've hit your usage limit", model=model)
        return ClaudeResult("ok", text=text, model=model,
                            usage={"input_tokens": 5000, "output_tokens": 3000}, cost_usd=0.5)


class Collect:
    """Simulerat S1: skriver provunderlaget, eller returnerar prenumerationsgräns."""

    def __init__(self, *statuses):
        self.statuses = list(statuses) or ["ok"]
        self.calls = 0

    def __call__(self, run_dir, protocol, runner=None):
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else "ok"
        call = ClaudeResult("ok" if status == "ok" else status, model=MODEL_COLLECTOR,
                            usage={"input_tokens": 1200, "output_tokens": 300}, cost_usd=0.02)
        if status != "ok":
            return collector.CollectResult(status, message=f"prenumerationsgräns för {SECRET}",
                                           calls=[("S1_collect/1", call)])
        sm.write_sources(run_dir, tw.make_sources())
        (Path(run_dir) / "kallor").mkdir(exist_ok=True)
        (Path(run_dir) / "kallor" / "k03.md").write_text(tw.FULLTEXT_3, encoding="utf-8")
        return collector.CollectResult("ok", message=f"3 källor ({SECRET})", calls=[("S1_collect/1", call)],
                                       counts={"sources": 3})


def steps(runner, collect=None):
    return main.Steps(runner=runner, collect=collect or Collect(), analyse=rw.analyse,
                      revise=rw.revise, check=rw.check)


@pytest.fixture
def env(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    runs = tmp_path / "runs"
    monkeypatch.setenv("CLIO_RESEARCH_RUNS_DIR", str(runs))
    monkeypatch.setenv("CLIO_CONTACT_EMAIL", SECRET)
    monkeypatch.setattr(main, "INBOX_DIR", inbox)
    monkeypatch.setattr(main, "_setup", lambda: None)
    proto = dict(tw.PROTOCOL, niva="standard", spridning="intern", hypothesis=None,
                 search_strategy={"phases": []}, output={})
    (inbox / "clio-research-021.json").write_text(json.dumps(proto, ensure_ascii=False), encoding="utf-8")
    proto["question"] = dict(proto["question"], keywords_primary={"en": ["uap"]})
    (inbox / "clio-research-021.json").write_text(json.dumps(proto, ensure_ascii=False), encoding="utf-8")
    return {"inbox": inbox, "runs": runs}


def new_run(env, **override):
    state, run_dir, protocol = main.start_run("clio-research-021", env["inbox"], env["runs"])
    protocol.update(override)
    return state, run_dir, protocol


def log_text(run_dir):
    return (run_dir / rs.LOG_FILE).read_text(encoding="utf-8")


# ── Revisionsloopen ───────────────────────────────────────────────────────────

def test_approved_directly(env):
    state, run_dir, protocol = new_run(env)
    runner = Runner(GOOD)
    state = main.run_pipeline(state, run_dir, protocol, steps(runner))
    assert state.status == "ready_for_human" and main.exit_code(state) == 0
    assert state.draft_version == 1 and state.revision_round == 0
    assert [c["model"] for c in runner.calls] == [MODEL_ANALYST]
    assert (run_dir / "final.md").exists() and (run_dir / "03_lint_v1.md").exists()
    assert [h["status"] for h in state.history][:2] == ["collecting", "analysing"]

    log = log_text(run_dir)
    assert f"S1_collect/1  {MODEL_COLLECTOR}  in=1200  out=300" in log
    assert f"S2_analyse/v1  {MODEL_ANALYST}  in=5000  out=3000" in log
    assert "ref_checker.py inte byggd" in log and "granskaren inte byggd" in log
    assert SECRET not in log and "<kontaktadress>" in log
    assert state.usage["input_tokens"] == 6200


def test_approved_after_one_revision(env):
    state, run_dir, protocol = new_run(env)
    runner = Runner(BAD, GOOD)
    state = main.run_pipeline(state, run_dir, protocol, steps(runner))
    assert state.status == "ready_for_human"
    assert state.draft_version == 2 and state.revision_round == 1
    assert "MÅSTE" in runner.calls[1]["prompt"]                 # kravlistan skickas med
    lint1 = json.loads((run_dir / "03_lint_v1.json").read_text(encoding="utf-8"))
    assert lint1["status"] == "REVISE" and lint1["requirements"]
    assert "revising" in [h["status"] for h in state.history]


def test_max_rounds_gives_needs_human(env):
    state, run_dir, protocol = new_run(env)
    runner = Runner(BAD, BAD, BAD)
    state = main.run_pipeline(state, run_dir, protocol, steps(runner))
    assert state.status == "needs_human" and main.exit_code(state) == 4
    assert state.draft_version == 3 and state.revision_round == 2 and len(runner.calls) == 3
    assert "efter 2 revisionsvarv" in state.history[-1]["note"]
    assert not (run_dir / "final.md").exists()


def test_protocol_max_revisions_zero(env):
    state, run_dir, protocol = new_run(env, max_revisions=0)
    state = main.run_pipeline(state, run_dir, protocol, steps(Runner(BAD)))
    assert state.status == "needs_human" and state.draft_version == 1


def test_no_sources_gives_needs_human(env):
    state, run_dir, protocol = new_run(env)
    empty = lambda run_dir, protocol, runner=None: collector.CollectResult("ok", counts={"sources": 0})
    state = main.run_pipeline(state, run_dir, protocol, steps(Runner(), empty))
    assert state.status == "needs_human" and "inga källor" in state.history[-1]["note"]


# ── Paus och återupptagning ───────────────────────────────────────────────────

def test_pause_in_s1_and_resume(env):
    state, run_dir, protocol = new_run(env)
    collect = Collect("limit", "ok")
    state = main.run_pipeline(state, run_dir, protocol, steps(Runner(), collect))
    assert state.status == "paused_limit" and state.paused_step == "S1_collect"
    assert main.exit_code(state) == 3
    assert SECRET not in json.dumps(state.history) and SECRET not in log_text(run_dir)

    state, run_dir, protocol = main.open_run(state.run_id, env["runs"])
    assert main.prepare_resume(state, run_dir)
    assert state.current_step == "S1_collect" and state.paused_step is None
    state = main.run_pipeline(state, run_dir, protocol, steps(Runner(GOOD), collect))
    assert state.status == "ready_for_human" and collect.calls == 2


def test_pause_during_revision_resumes_same_step(env):
    state, run_dir, protocol = new_run(env)
    state = main.run_pipeline(state, run_dir, protocol, steps(Runner(BAD, "LIMIT")))
    assert state.status == "paused_limit" and state.paused_step == "S2_analyse"
    assert state.draft_version == 1 and state.revision_round == 1

    state, run_dir, protocol = main.open_run(state.run_id, env["runs"])
    main.prepare_resume(state, run_dir)
    collect = Collect()
    runner = Runner(GOOD)
    state = main.run_pipeline(state, run_dir, protocol, steps(runner, collect))
    assert collect.calls == 0                                   # S1 körs inte om
    assert state.status == "ready_for_human"
    assert state.draft_version == 2 and state.revision_round == 1
    assert "MÅSTE" in runner.calls[0]["prompt"]                  # fortsatte med revisionen


def test_resume_needs_human_requires_force(env):
    state, run_dir, protocol = new_run(env, max_revisions=0)
    state = main.run_pipeline(state, run_dir, protocol, steps(Runner(BAD)))
    assert not main.prepare_resume(state, run_dir)
    assert main.prepare_resume(state, run_dir, force=True)


# ── Kommandoraden ─────────────────────────────────────────────────────────────

def test_cli_run_and_resume(env, monkeypatch, capsys):
    fakes = {"runner": Runner("LIMIT")}
    monkeypatch.setattr(main, "default_steps", lambda: steps(fakes["runner"]))
    assert main.main(["--protocol", "clio-research-021"]) == 3
    run_id = next(env["runs"].iterdir()).name
    assert (env["runs"] / run_id / main.PROTOCOL_JSON).exists()

    fakes["runner"] = Runner(GOOD)
    assert main.main(["--resume", run_id]) == 0
    assert main.main(["--resume", run_id]) == 0                 # redan klar: inget att göra
    assert "inget att återuppta" in capsys.readouterr().out
    assert main.main(["--status", run_id]) == 0


def test_cli_level_override(env, monkeypatch):
    runner = Runner(GOOD)
    monkeypatch.setattr(main, "default_steps", lambda: steps(runner))
    main.main(["--protocol", "clio-research-021", "--niva", "snabb"])
    run_dir = next(env["runs"].iterdir())
    assert json.loads((run_dir / main.PROTOCOL_JSON).read_text(encoding="utf-8"))["niva"] == "snabb"
    assert runner.calls[0]["model"] == rw.MODEL_BY_LEVEL["snabb"]


def test_cli_incomplete_protocol_is_clear_error(env, capsys):
    (env["inbox"] / "clio-research-050.md").write_text("## METADATA\n\n```\nRun-ID: clio-research-050\n```\n",
                                                       encoding="utf-8")
    assert main.main(["--protocol", "clio-research-050"]) == 2
    err = capsys.readouterr().err
    assert "Protokollet är ofullständigt" in err and "huvudfrågan saknas" in err
    assert not env["runs"].exists() or not any(env["runs"].iterdir())


def test_cli_legacy_flag_uses_old_flow(env, monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(main, "_legacy_run", lambda pid, resume_run_id: called.append(pid))
    for name in ("RUNNING_DIR", "DONE_DIR"):
        monkeypatch.setattr(main, name, tmp_path / name)
    assert main.main(["--legacy", "--protocol", "clio-research-021"]) == 0
    assert called == ["clio-research-021"]
