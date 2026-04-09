"""
models.py — Lightweight dataclasses for clio-partnerdb entities.

These mirror the DB schema but are not ORM objects. Use db.py helpers
to read/write. Models are used for type hints and structured passing
between functions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Partner:
    id: str
    created_at: str
    editors: list = field(default_factory=list)
    is_person: bool = True
    is_org: bool = False

    @classmethod
    def from_row(cls, row) -> "Partner":
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            editors=json.loads(row["editors"] or "[]"),
            is_person=bool(row["is_person"]),
            is_org=bool(row["is_org"]),
        )


@dataclass
class Event:
    id: str
    partner_id: str
    type: str                       # 'birth'|'death'|'marriage'|'move'|…
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    date_precision: Optional[str] = None   # 'year'|'month'|'day'|'approximate'
    place: Optional[str] = None
    place_lat: Optional[float] = None
    place_lon: Optional[float] = None
    source_id: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Event":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})


@dataclass
class Claim:
    id: str
    partner_id: str
    predicate: str
    value: str                      # JSON string
    asserted_at: str
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    is_primary: bool = False
    source_id: Optional[str] = None
    asserted_by: Optional[str] = None

    def parsed_value(self):
        """Return value decoded from JSON."""
        try:
            return json.loads(self.value)
        except (json.JSONDecodeError, TypeError):
            return self.value

    @classmethod
    def from_row(cls, row) -> "Claim":
        return cls(
            id=row["id"],
            partner_id=row["partner_id"],
            predicate=row["predicate"],
            value=row["value"],
            asserted_at=row["asserted_at"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            is_primary=bool(row["is_primary"]),
            source_id=row["source_id"],
            asserted_by=row["asserted_by"],
        )


@dataclass
class Relationship:
    id: str
    from_id: str
    to_id: str
    type: str
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    source_id: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Relationship":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})


@dataclass
class Source:
    id: str
    type: str
    imported_at: str
    reference: Optional[str] = None
    imported_by: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Source":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})


@dataclass
class Watch:
    owner_email: str
    partner_id: str
    priority: str       # 'important'|'normal'|'nice_to_know'
    added_at: str
    source: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Watch":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})


# Priority translation helpers (DB uses English, display uses Swedish)
_TO_SWEDISH = {
    "important":    "viktig",
    "normal":       "normal",
    "nice_to_know": "bra_att_veta",
}
_TO_ENGLISH = {v: k for k, v in _TO_SWEDISH.items()}


def priority_to_swedish(english: str) -> str:
    return _TO_SWEDISH.get(english, english)


def priority_to_english(swedish: str) -> str:
    return _TO_ENGLISH.get(swedish, swedish)
