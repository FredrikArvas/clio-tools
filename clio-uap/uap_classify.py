"""uap_classify.py — Klassificerar clio.media.article efter UAP-relevans via Claude."""

from __future__ import annotations

import json
import logging
import re
import time

import config
from odoo_sync import get_env

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_BATCHES_PER_RUN = 10       # hårt tak: max 500 artiklar/körning
MAX_RUNTIME_SECONDS = 20 * 60  # hårt tak: avbryt efter 20 min oavsett
MAX_TOKENS = 2048

_PROMPT_TEMPLATE = """Klassificera artiklarna nedan efter UAP-relevans.
Svara ENBART med en JSON-array: [{{"id": 123, "relevance_class": "confirmed"}}, ...]

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
    import anthropic

    env = get_env()
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
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

        results = _classify_batch(client, rows)
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


def _classify_batch(client, rows: list[dict]) -> list[dict]:
    articles_json = json.dumps(
        [{"id": r["id"], "title": r.get("title") or "",
          "snippet": (r.get("body_snippet") or "")[:300]} for r in rows],
        ensure_ascii=False,
    )
    prompt = _PROMPT_TEMPLATE.format(articles_json=articles_json)

    try:
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
    except Exception as e:
        logger.warning("[uap_classify] Claude-anrop misslyckades: %s", e)
        return []

    return _parse_response(raw, valid_ids={r["id"] for r in rows})


def _parse_response(raw: str, valid_ids: set[int]) -> list[dict]:
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        logger.warning("[uap_classify] Inget JSON-block hittades i svaret")
        return []
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError as e:
        logger.warning("[uap_classify] JSON-parsning misslyckades: %s", e)
        return []

    valid_classes = {"confirmed", "likely", "uncertain", "off_topic"}
    return [
        r for r in parsed
        if r.get("id") in valid_ids and r.get("relevance_class") in valid_classes
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
