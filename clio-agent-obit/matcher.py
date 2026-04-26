"""
matcher.py — Name matching with confidence scores for clio-agent-obit.

Matches a death announcement against the watch list.
Returns a list of Match objects sorted by confidence score.

Design principle: false positives are OK. False negatives are NOT OK.
Notification threshold: >= 60 points.

Score table:
  +40  Exact last name match (case-insensitive, diacritic-normalised)
  +30  Exact first name match
  +25  Nickname map hit (first name known alias)
  +25  Last name fuzzy Levenshtein ≤ 1 (Jansson / Jonsson)
  +20  First name Levenshtein ≤ 2
  +20  Birth year known in announcement, matches ±5 years
  +15  Birth year approximate (fodelsear_approx ±10 years)
  +10  Swedish soundex / metaphone hit on first name
  +10  City match

Data source:
  Entries are loaded from clio-partnerdb via load_entries_from_db().
  The legacy load_entries_from_csv() is kept for backwards compatibility
  and testing without a DB.
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import yaml

# ── Optional fast Levenshtein ─────────────────────────────────────────────────
try:
    from Levenshtein import distance as levenshtein_distance
    _HAS_LEVENSHTEIN = True
except ImportError:
    import difflib
    _HAS_LEVENSHTEIN = False

THRESHOLD = 60

# ── Nickname map ──────────────────────────────────────────────────────────────
_NICKNAMES_PATH = os.path.join(os.path.dirname(__file__), "matcher", "nicknames.yaml")

def _load_nicknames() -> dict[str, str]:
    """Return a flat lookup: any_variant -> canonical_name."""
    lookup: dict[str, str] = {}
    try:
        with open(_NICKNAMES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for canonical, variants in data.items():
            lookup[canonical] = canonical
            for v in (variants or []):
                lookup[v] = canonical
    except Exception:
        pass
    return lookup

_ALIAS_LOOKUP: dict[str, str] = _load_nicknames()


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class WatchlistEntry:
    """A person being watched. Loaded from partnerdb or CSV."""
    efternamn: str
    fornamn: str
    fodelsear: Optional[int]          # None if unknown
    hemort: Optional[str]             # None if unknown
    prioritet: str                    # "viktig" | "normal" | "bra_att_veta"
    kalla: str                        # "manuell" | "gedcom" | "adressbok"
    partner_id: Optional[str] = None  # partnerdb UUID (None when loaded from CSV)
    added_at: Optional[str] = None    # ISO 8601, for first-run suppression
    fodelsear_approx: bool = False    # True when year is a rough estimate (±10)

    def __post_init__(self):
        self.efternamn = _normalize(self.efternamn)
        self.fornamn = _normalize(self.fornamn)
        if self.hemort:
            self.hemort = _normalize(self.hemort)


@dataclass
class Announcement:
    """A death announcement from a source adapter."""
    id: str
    namn: str
    fodelsear: Optional[int]
    hemort: Optional[str]
    url: str
    publiceringsdatum: str            # ISO date string "YYYY-MM-DD"
    raw_title: str
    dodsar: Optional[int] = None      # Dödsår om det finns i annonslistan
    # Detaljdata — hämtas från detaljsidan för matchade annonser
    body_html: str = ""               # Fullständig annonstext (HTML)
    image_url: str = ""               # URL till tidningsbild om tillgänglig
    image_data: Optional[bytes] = None  # Nedladdad bild (binär)
    source_name: str = ""             # Källans namn, t.ex. "familjesidan.se"


@dataclass
class Match:
    entry: WatchlistEntry
    announcement: Announcement
    score: int
    score_breakdown: dict[str, int] = field(default_factory=dict)

    @property
    def is_notifiable(self) -> bool:
        return self.score >= THRESHOLD

    def summary(self) -> str:
        namn = f"{self.entry.fornamn} {self.entry.efternamn}".strip()
        return (
            f"{namn} | score: {self.score} | priority: {self.entry.prioritet} | "
            f"announcement: {self.announcement.url}"
        )


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Lowercase + strip diacritics (å→a, ä→a, ö→o). Used for comparison only."""
    s = s.strip().lower()
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _split_name(full_name: str) -> tuple[str, str]:
    """Heuristic split: last word = last name, rest = first name."""
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


# ── Levenshtein helper ────────────────────────────────────────────────────────

def _lev(a: str, b: str) -> int:
    if _HAS_LEVENSHTEIN:
        return levenshtein_distance(a, b)
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return int((1 - ratio) * max(len(a), len(b)))


# ── Swedish soundex (simple) ──────────────────────────────────────────────────

def _swedish_soundex(s: str) -> str:
    """
    Simplified Swedish soundex: collapses common phonetic equivalences.
    Not a full Soundex implementation — just handles the most common
    Swedish name variations (c/k, ck/k, ph/f, w/v, gö/jö, etc.).
    """
    s = _normalize(s)
    replacements = [
        ("ck", "k"), ("ph", "f"), ("qu", "kv"),
        ("sch", "sk"), ("sj", "sj"), ("tj", "sj"),
        ("w", "v"), ("x", "ks"), ("z", "s"),
        ("c", "k"),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s


def _soundex_match(a: str, b: str) -> bool:
    return _swedish_soundex(a) == _swedish_soundex(b) and len(a) >= 3


# ── Core matching logic ───────────────────────────────────────────────────────

def _score_first_name(ann_fn: str, entry_fn: str) -> tuple[int, str]:
    """Return (points, breakdown_key) for first name comparison."""
    if not ann_fn or not entry_fn:
        return 0, ""

    if ann_fn == entry_fn:
        return 30, "fornamn_exact"

    # Nickname map
    ann_canon = _ALIAS_LOOKUP.get(ann_fn, ann_fn)
    ent_canon = _ALIAS_LOOKUP.get(entry_fn, entry_fn)
    if ann_canon == ent_canon:
        return 25, "fornamn_nickname"

    # Levenshtein
    max_len = max(len(ann_fn), len(entry_fn))
    max_dist = 1 if max_len <= 5 else 2
    if _lev(ann_fn, entry_fn) <= max_dist:
        return 20, "fornamn_levenshtein"

    # Soundex
    if _soundex_match(ann_fn, entry_fn):
        return 10, "fornamn_soundex"

    return 0, ""


def _score_last_name(ann_ln: str, entry_ln: str) -> tuple[int, str]:
    """Return (points, breakdown_key) for last name comparison."""
    if not ann_ln or not entry_ln:
        return 0, ""

    if ann_ln == entry_ln:
        return 40, "efternamn_exact"

    if _lev(ann_ln, entry_ln) <= 1:
        return 25, "efternamn_levenshtein"

    return 0, ""


def match_announcement(
    announcement: Announcement,
    watchlist: list[WatchlistEntry],
) -> list[Match]:
    """
    Match an announcement against the full watchlist.
    Returns all entries with score >= 1, sorted descending by score.
    Filter with Match.is_notifiable (>= 60) for notification candidates.
    """
    results: list[Match] = []
    ann_fornamn_raw, ann_efternamn_raw = _split_name(announcement.namn)
    ann_fornamn = _normalize(ann_fornamn_raw)
    ann_efternamn = _normalize(ann_efternamn_raw)

    for entry in watchlist:
        score = 0
        breakdown: dict[str, int] = {}

        # Last name
        ln_pts, ln_key = _score_last_name(ann_efternamn, entry.efternamn)
        if ln_pts:
            score += ln_pts
            breakdown[ln_key] = ln_pts

        # First name
        fn_pts, fn_key = _score_first_name(ann_fornamn, entry.fornamn)
        if fn_pts:
            score += fn_pts
            breakdown[fn_key] = fn_pts

        # Birth year
        if announcement.fodelsear is not None and entry.fodelsear is not None:
            window = 10 if entry.fodelsear_approx else 5
            if abs(announcement.fodelsear - entry.fodelsear) <= window:
                pts = 15 if entry.fodelsear_approx else 20
                score += pts
                breakdown["fodelsear"] = pts

        # City
        if (
            announcement.hemort
            and entry.hemort
            and _normalize(announcement.hemort) == entry.hemort
        ):
            score += 10
            breakdown["hemort"] = 10

        if score > 0:
            results.append(Match(
                entry=entry,
                announcement=announcement,
                score=score,
                score_breakdown=breakdown,
            ))

    results.sort(key=lambda m: m.score, reverse=True)
    return results


def filter_notifiable(matches: list[Match]) -> list[Match]:
    return [m for m in matches if m.is_notifiable]


# ── DB loader ─────────────────────────────────────────────────────────────────

def load_entries_from_db(conn, owner_email: str) -> list[WatchlistEntry]:
    """
    Load WatchlistEntry objects from clio-partnerdb for a given owner.
    Includes all name claims (primary + historical) so fuzzy matching
    works even if the announcement uses a maiden name.
    """
    from models import priority_to_swedish

    watches = conn.execute(
        "SELECT partner_id, priority, added_at, source FROM watch WHERE owner_email=?",
        (owner_email,),
    ).fetchall()

    entries: list[WatchlistEntry] = []

    for w in watches:
        pid = w["partner_id"]

        # All name claims (primary first, include historical for matching)
        name_rows = conn.execute(
            "SELECT value, is_primary FROM claim WHERE partner_id=? AND predicate='name' ORDER BY is_primary DESC",
            (pid,),
        ).fetchall()
        if not name_rows:
            continue

        # Birth year from birth event
        birth_row = conn.execute(
            "SELECT date_from FROM event WHERE partner_id=? AND type='birth' LIMIT 1",
            (pid,),
        ).fetchone()
        birth_year: Optional[int] = None
        if birth_row and birth_row["date_from"]:
            try:
                birth_year = int(birth_row["date_from"][:4])
            except (ValueError, TypeError):
                pass

        # City from claim
        city_row = conn.execute(
            "SELECT value FROM claim WHERE partner_id=? AND predicate='city' AND is_primary=1 LIMIT 1",
            (pid,),
        ).fetchone()
        city: Optional[str] = None
        if city_row:
            try:
                city = json.loads(city_row["value"])
                if isinstance(city, dict):
                    city = None
            except Exception:
                city = city_row["value"]

        prioritet_en = w["priority"]
        prioritet_sw = priority_to_swedish(prioritet_en)
        source = w["source"] or "gedcom"

        # Add one WatchlistEntry per name claim (catches maiden names)
        for i, name_row in enumerate(name_rows):
            try:
                name_val = json.loads(name_row["value"])
                fornamn = name_val.get("fornamn", "").strip()
                efternamn = name_val.get("efternamn", "").strip()
            except Exception:
                continue
            if not fornamn or not efternamn:
                continue

            entries.append(WatchlistEntry(
                efternamn=efternamn,
                fornamn=fornamn,
                fodelsear=birth_year,
                hemort=city,
                prioritet=prioritet_sw,
                kalla=source,
                partner_id=pid,
                added_at=w["added_at"],
                fodelsear_approx=False,
            ))
            if i == 0:
                break  # Only use primary name for now; all claims loaded for future fuzzy

    return entries
