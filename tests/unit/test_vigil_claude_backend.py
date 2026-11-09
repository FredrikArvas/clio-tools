"""Claude via prenumerationen (`claude -p`) i clio-vigil, 2026-11-08/09.

claude_backend delas av summarizern och UAP-klassificeraren.
- Summarizern: Ollama är standard; priority_score >= CLAUDE_THRESHOLD går till
  Sonnet. Fel eller kvotgräns ger Ollama.
- Klassificeraren: Sonnet. Vid kvotgräns eller fel väntar posten (queued) —
  kvalitet går före tid.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clio-vigil"))

import claude_backend  # noqa: E402
import orchestrator  # noqa: E402
import summarizer  # noqa: E402
from classifiers import uap_classifier, uap_pipeline  # noqa: E402

LONG_TEXT = "Pentagon released new UAP files with radar data. " * 12
FOOTER = "\n\n---\n📊 Tokens: ~120 (svar) | ~400 (session)\n🎪 *Ett skämt*"


class FakeRunner:
    STATUS_OK = "ok"
    STATUS_LIMIT = "limit"
    STATUS_ERROR = "error"

    def __init__(self, status="ok", text="Sammanfattning."):
        self.status = status
        self.text = text
        self.calls = []

    def run_claude(self, role, prompt, model, workdir, system_prompt=None,
                   max_turns=None, timeout_s=None):
        self.calls.append({"role": role, "prompt": prompt, "model": model,
                           "system_prompt": system_prompt, "max_turns": max_turns})
        return SimpleNamespace(status=self.status, is_ok=self.status == self.STATUS_OK,
                               text=self.text, message=f"status {self.status}")


@pytest.fixture
def runner(monkeypatch, tmp_path):
    fake = FakeRunner()
    monkeypatch.setattr(claude_backend, "load_runner", lambda: fake)
    monkeypatch.setattr(claude_backend, "_is_limited", False)
    monkeypatch.setattr(claude_backend, "CLAUDE_WORKDIR", tmp_path / "claude-work")
    monkeypatch.setattr(summarizer, "CLAUDE_BACKEND", summarizer.BACKEND_SUBSCRIPTION)
    return fake


@pytest.fixture
def conn(tmp_path):
    c = orchestrator.init_db(tmp_path / "vigil.db")
    yield c
    c.close()


def _add(conn, url, priority):
    item_id = orchestrator.upsert_item(conn, url=url, domain="ufo",
                                       source_type="rss", title=f"Title {url}")
    conn.execute("UPDATE vigil_items SET state='indexed', description=?, priority_score=? "
                 "WHERE id=?", (LONG_TEXT, priority, item_id))
    conn.commit()
    return item_id


def _item():
    return {"id": 1, "domain": "ufo", "title": "T", "url": "https://x",
            "source_name": "S", "published_at": "2026-11-08"}


# --- claude_backend.strip_cli_extras -----------------------------------------------------

def test_strip_removes_token_footer_and_joke():
    assert claude_backend.strip_cli_extras("Rad ett.\nRad två." + FOOTER) == "Rad ett.\nRad två."


def test_strip_keeps_clean_text():
    assert claude_backend.strip_cli_extras("  Ren text.  ") == "Ren text."


# --- summarizer via claude_backend ---------------------------------------------

def test_subscription_returns_stripped_summary(runner):
    runner.text = "Sonnet-sammanfattning." + FOOTER

    summary = summarizer._summarize_with_claude(_item(), LONG_TEXT)

    assert summary == "Sonnet-sammanfattning."
    call = runner.calls[0]
    assert call["role"] == "analyst"
    assert call["model"] == summarizer.CLAUDE_MODEL == claude_backend.MODEL_SONNET
    assert call["max_turns"] == 1
    assert claude_backend.OUTPUT_ONLY_INSTRUCTION in call["system_prompt"]


def test_limit_stops_further_calls_for_the_run(runner):
    runner.status = FakeRunner.STATUS_LIMIT

    with pytest.raises(claude_backend.SubscriptionLimitError):
        summarizer._summarize_with_claude(_item(), LONG_TEXT)
    assert claude_backend.is_limited() is True

    with pytest.raises(RuntimeError):
        summarizer._summarize_with_claude(_item(), LONG_TEXT)
    assert len(runner.calls) == 1        # andra anropet når aldrig claude -p


def test_error_status_raises(runner):
    runner.status = FakeRunner.STATUS_ERROR
    with pytest.raises(RuntimeError):
        summarizer._summarize_with_claude(_item(), LONG_TEXT)
    assert claude_backend.is_limited() is False


def test_only_footer_counts_as_empty(runner):
    runner.text = FOOTER
    with pytest.raises(RuntimeError):
        summarizer._summarize_with_claude(_item(), LONG_TEXT)


def test_api_backend_skips_runner(runner, monkeypatch):
    monkeypatch.setattr(summarizer, "CLAUDE_BACKEND", summarizer.BACKEND_API)
    monkeypatch.setattr(summarizer, "_call_claude_api", lambda system, user: "API-svar")

    assert summarizer._summarize_with_claude(_item(), LONG_TEXT) == "API-svar"
    assert runner.calls == []


# --- routing i summarize_item ----------------------------------------------

def test_high_priority_goes_to_claude(runner, conn, monkeypatch):
    monkeypatch.setattr(summarizer, "_summarize_with_ollama", lambda item, text: "OLLAMA")
    item_id = _add(conn, "hi", priority=summarizer.CLAUDE_THRESHOLD)

    assert summarizer.summarize_item(conn, item_id) == "Sammanfattning."
    assert len(runner.calls) == 1


def test_low_priority_stays_local(runner, conn, monkeypatch):
    monkeypatch.setattr(summarizer, "LOCAL_MODEL", "qwen2.5:3b")
    monkeypatch.setattr(summarizer, "_summarize_with_ollama", lambda item, text: "OLLAMA")
    item_id = _add(conn, "lo", priority=0.1)

    assert summarizer.summarize_item(conn, item_id) == "OLLAMA"
    assert runner.calls == []


def test_claude_failure_falls_back_to_ollama(runner, conn, monkeypatch):
    runner.status = FakeRunner.STATUS_LIMIT
    monkeypatch.setattr(summarizer, "_summarize_with_ollama", lambda item, text: "OLLAMA")
    item_id = _add(conn, "hi", priority=0.9)

    assert summarizer.summarize_item(conn, item_id) == "OLLAMA"
    row = conn.execute("SELECT summary FROM vigil_items WHERE id=?", (item_id,)).fetchone()
    assert row["summary"] == "OLLAMA"


def test_real_claude_runner_loads(monkeypatch):
    """Den riktiga claude_runner ska gå att ladda (dataclass kräver sys.modules-registrering)."""
    monkeypatch.setattr(claude_backend, "_runner", None)
    module = claude_backend.load_runner()
    assert module.STATUS_LIMIT and callable(module.run_claude)


# --- UAP-klassificeraren -----------------------------------------------------

CLASSIFICATION_JSON = (
    '{"encounter_class": "3", "discourse_level": "4", "official_response": "D", '
    '"confidence": 0.85, "summary": "Radarspår.", "reasoning": "Mätdata finns."}'
)


def test_classifier_uses_sonnet_and_parses_json(runner):
    runner.text = "Här är svaret:\n" + CLASSIFICATION_JSON + FOOTER

    result = uap_classifier.classify("Radar UAP", LONG_TEXT)

    assert runner.calls[0]["model"] == claude_backend.MODEL_SONNET
    assert result["error"] is None
    assert result["encounter_class"] == "3"
    assert result["import_candidate"] is True


def test_classifier_unparseable_answer_gives_error_result(runner):
    runner.text = "Jag kan inte klassificera detta."
    result = uap_classifier.classify("T", LONG_TEXT)
    assert result["error"] and result["import_candidate"] is False


def test_classifier_normalizes_invalid_values(runner):
    runner.text = '{"encounter_class": 7, "discourse_level": "x", "confidence": 3}'
    result = uap_classifier.classify("T", LONG_TEXT)
    assert result["encounter_class"] is False
    assert result["discourse_level"] == "1"
    assert result["confidence"] == 1.0


def _add_queued(conn, url):
    item_id = orchestrator.upsert_item(conn, url=url, domain="ufo",
                                       source_type="rss", title=f"Title {url}")
    conn.execute("UPDATE vigil_items SET state='queued', description=? WHERE id=?",
                 (LONG_TEXT, item_id))
    conn.commit()
    return item_id


def _state(conn, item_id):
    return conn.execute("SELECT state FROM vigil_items WHERE id=?", (item_id,)).fetchone()[0]


def test_pipeline_quota_limit_leaves_items_queued(runner, conn):
    runner.status = FakeRunner.STATUS_LIMIT
    ids = [_add_queued(conn, f"q{n}") for n in range(3)]

    counts = uap_pipeline.run_uap_classifier(conn, odoo_env=None)

    assert counts["deferred"] == 3
    assert len(runner.calls) == 1                 # avbryter efter första kvotsvaret
    assert [_state(conn, i) for i in ids] == ["queued"] * 3


def test_pipeline_runner_error_leaves_item_queued(runner, conn):
    runner.status = FakeRunner.STATUS_ERROR
    item_id = _add_queued(conn, "q1")

    counts = uap_pipeline.run_uap_classifier(conn, odoo_env=None)

    assert counts["errors"] == 1
    assert _state(conn, item_id) == "queued"


def test_pipeline_non_candidate_is_marked_classified(runner, conn):
    runner.text = CLASSIFICATION_JSON.replace('"3"', '"N"')
    item_id = _add_queued(conn, "q1")

    counts = uap_pipeline.run_uap_classifier(conn, odoo_env=None)

    assert counts["skipped"] == 1
    assert _state(conn, item_id) == "uap_classified"
