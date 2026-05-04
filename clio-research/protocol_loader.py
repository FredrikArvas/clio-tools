"""protocol_loader.py — Validerar och normaliserar protokoll-JSON, genererar run_id."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


REQUIRED_FIELDS = ["protocol_id", "question", "search_strategy", "output"]
REQUIRED_QUESTION_FIELDS = ["natural_language", "keywords_primary"]


def load(protocol_id: str, inbox_dir: Path) -> dict:
    """Läs, validera och normalisera protokollfil. Returnerar protokoll-dict med run_id."""
    path = inbox_dir / f"{protocol_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Protokollfil saknas: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    _validate(data, path)
    _normalize(data)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    data["run_id"] = f"{data['protocol_id']}_{ts}"

    return data


def _validate(data: dict, path: Path) -> None:
    for field in REQUIRED_FIELDS:
        if field not in data:
            raise ValueError(f"Protokollfil {path} saknar obligatoriskt fält: '{field}'")

    q = data.get("question", {})
    for field in REQUIRED_QUESTION_FIELDS:
        if field not in q:
            raise ValueError(f"question.{field} saknas i protokollfilen")


def _normalize(data: dict) -> None:
    q = data["question"]

    q.setdefault("keywords_adjacent", {})
    q.setdefault("keywords_adversarial", {})
    q.setdefault("key_researchers", [])

    ss = data.get("search_strategy", {})
    ss.setdefault("phases", [])
    ss.setdefault("regions", ["US", "EU"])
    ss.setdefault("tier3_databases", [])

    data.setdefault("credibility_dimensions", [
        "methodological_rigor",
        "institutional_independence",
        "geographic_convergence",
        "internal_consistency",
        "falsification_attempts",
        "temporal_stability",
    ])

    out = data.get("output", {})
    out.setdefault("format", "narrative_with_evidence_layers")
    out.setdefault("deliver_to", "fredrik@arvas.se")
    out.setdefault("status_updates", True)
    out.setdefault("index_in_qdrant", True)
    out.setdefault("qdrant_collection", "vigil_research")


def source_id(title: str, year: int | None, doi: str | None) -> str:
    """Deterministisk sha256-baserad source_id för deduplicering."""
    key = f"{(title or '').lower().strip()}|{year or ''}|{(doi or '').lower().strip()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]
