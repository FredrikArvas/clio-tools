"""uap_classify.py — Klassificerar clio.media.article efter UAP-relevans via Claude.

Använder claude-CLI:t (subprocess, prenumerationsbaserat) — inte anthropic-SDK:t —
så att bulk-klassificeringen inte drar separata API-tokens.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time

from odoo_sync import get_env

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_BATCHES_PER_RUN = 10        # hårt tak: max 500 artiklar/körning
MAX_RUNTIME_SECONDS = 20 * 60   # hårt tak: avbryt efter 20 min oavsett
CLAUDE_TIMEOUT_SECONDS = 120    # hårt tak per claude-anrop
CLAUDE_MODEL_CLI = "sonnet"

_VALID_CLASSES = ("confirmed", "likely", "uncertain", "off_topic")

_JSON_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "relevance_class": {"type": "string", "enum": list(_VALID_CLASSES)},
                },
                "required": ["id", "relevance_class"],
            },
        },
    },
    "required": ["classifications"],
})

_PROMPT_TEMPLATE = """Klassificera artiklarna nedan efter UAP-relevans.

Tillåtna värden:
  confirmed  - nämner kända fall: AARO, Grusch, Nimitz, GOFAST, GIMBAL, Rendlesham,
               UAP Congressional Hearings, Pentagon UFO
  likely     - UAP/UFO-observation med konkret kontext (plats, datum, vittne)
  uncertain  - nämner bara "UFO"/"UAP" utan specifik kontext
  off_topic  - spel, film, TV-serie, konsert, försäkring, resa - inget med UAP att göra

Artiklar:
{articles_json}
"""


def classify_unclassified(dry_run: bool = False) -> int:
    env = get_env()
    Article = env["clio.media.article"]

    start = time.monotonic()
    total = 0

    for batch_num in range(MAX_BATCHES_PER_RUN):
        if time.monotonic() - start > MAX_RUNTIME_SECONDS:
            logger.warning("[uap_classify] Tidsgräns nådd (%ds) — avbryter", MAX_RUNTIME_SECONDS)
            break

        rows = Article.search_read(
            [("relevance_class", "=", "not_classified")],
            ["id", "title", "body_snippet"],
            limit=BATCH_SIZE,
        )
        if not rows:
            logger.info("[uap_classify] Inga fler oklassificerade artiklar.")
            break

        results = _classify_batch(rows)
        if not results:
            logger.warning(
                "[uap_classify] Batch %d gav inget resultat — avbryter (undviker oändlig loop)",
                batch_num,
            )
            break

        if not dry_run:
            _write_results(Article, results)
        total += len(results)
        logger.info("[uap_classify] Batch %d: %d artiklar klassificerade", batch_num, len(results))

    logger.info("[uap_classify] Klart. %d artiklar klassificerade totalt.", total)
    return total


def _classify_batch(rows: list[dict]) -> list[dict]:
    articles_json = json.dumps(
        [{"id": r["id"], "title": r.get("title") or "",
          "snippet": (r.get("body_snippet") or "")[:300]} for r in rows],
        ensure_ascii=False,
    )
    prompt = _PROMPT_TEMPLATE.format(articles_json=articles_json)

    try:
        proc = subprocess.run(
            ["claude", "--print", "--model", CLAUDE_MODEL_CLI,
             "--output-format", "json", "--json-schema", _JSON_SCHEMA, prompt],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[uap_classify] claude-CLI tog för lång tid (>%ds)", CLAUDE_TIMEOUT_SECONDS)
        return []
    except FileNotFoundError:
        logger.warning("[uap_classify] claude-CLI hittades inte i PATH")
        return []

    if proc.returncode != 0:
        logger.warning("[uap_classify] claude-CLI avslutade med kod %d: %s",
                        proc.returncode, proc.stderr[:300])
        return []

    return _parse_response(proc.stdout, valid_ids={r["id"] for r in rows})


def _parse_response(raw: str, valid_ids: set[int]) -> list[dict]:
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("[uap_classify] Kunde inte tolka claude-CLI:ts JSON-kuvert: %s", e)
        return []

    if envelope.get("is_error"):
        logger.warning("[uap_classify] claude-CLI rapporterade fel: %s", envelope.get("result"))
        return []

    parsed = (envelope.get("structured_output") or {}).get("classifications")
    if not parsed:
        logger.warning("[uap_classify] Inget structured_output i svaret")
        return []

    return [
        r for r in parsed
        if r.get("id") in valid_ids and r.get("relevance_class") in _VALID_CLASSES
    ]


def _write_results(Article, results: list[dict]) -> None:
    by_class: dict[str, list[int]] = {}
    for r in results:
        by_class.setdefault(r["relevance_class"], []).append(r["id"])
    for cls, ids in by_class.items():
        Article.write(ids, {"relevance_class": cls})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    classify_unclassified()
