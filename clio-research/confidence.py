"""
confidence.py — Konfidensmodell för clio-research.

Beräknar konfidens per fält baserat på källtyp och konvergens (ADR-006).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# Grundkonfidens per källtyp (ADR-006)
BASE_CONFIDENCE: dict[str, float] = {
    "gedcom": 0.95,
    "wikidata": 0.60,
    "wikipedia": 0.60,
    "libris": 0.65,
    "manuell": 0.80,
    "inferens": 0.30,
}

# Tröskelvärde för auto-godkännande (ADR-006)
CONFIDENCE_THRESHOLD = 0.70

# Konvergenskonfidens: ≥2 oberoende källor rapporterar samma värde (ADR-006)
CONVERGENCE_CONFIDENCE = 0.85


@dataclass
class FieldSource:
    """Källreferens för ett enskilt fält (ADR-002)."""
    typ: str
    url: Optional[str] = None
    hämtad: Optional[str] = None
    konfidens: float = 0.0
    notat: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "typ": self.typ,
            "url": self.url,
            "hämtad": self.hämtad,
            "konfidens": self.konfidens,
            "notat": self.notat,
        }


@dataclass
class FieldValue:
    """Ett fält med värde och källreferens (ADR-002)."""
    värde: object = None
    källa: Optional[FieldSource] = None

    def to_dict(self) -> dict:
        return {
            "värde": self.värde,
            "källa": self.källa.to_dict() if self.källa else None,
        }

    @property
    def konfidens(self) -> float:
        if self.källa is None:
            return 0.0
        return self.källa.konfidens

    @property
    def needs_review(self) -> bool:
        return self.konfidens < CONFIDENCE_THRESHOLD and self.värde is not None


class ConfidenceModel:
    """
    Beräknar och hanterar konfidens för datapunkter (ADR-006).

    Användning:
        cm = ConfidenceModel()
        fv = cm.make_field("Dag Arvas", "wikidata", url="https://www.wikidata.org/wiki/Q5560391")
        cm.apply_convergence(fv, ["wikidata", "wikipedia"])
    """

    def base_confidence(self, source_type: str) -> float:
        """Returnerar grundkonfidens för en källtyp."""
        return BASE_CONFIDENCE.get(source_type, 0.0)

    def make_field(
        self,
        värde: object,
        source_type: str,
        url: Optional[str] = None,
        hämtad: Optional[str] = None,
        notat: Optional[str] = None,
    ) -> FieldValue:
        """Skapar ett FieldValue med korrekt konfidens."""
        konfidens = self.base_confidence(source_type)
        src = FieldSource(
            typ=source_type,
            url=url,
            hämtad=hämtad,
            konfidens=konfidens,
            notat=notat,
        )
        return FieldValue(värde=värde, källa=src)

    def apply_convergence(self, field: FieldValue, confirming_sources: list[str]) -> FieldValue:
        """
        Höjer konfidens till CONVERGENCE_CONFIDENCE om ≥2 oberoende källor
        bekräftar samma värde (ADR-006: konvergensregel).

        confirming_sources: lista av källtyper som bekräftar värdet (inkl. primärkällan).
        """
        if field.källa is None:
            return field
        unique_sources = set(confirming_sources)
        if len(unique_sources) >= 2:
            field.källa.konfidens = CONVERGENCE_CONFIDENCE
            if field.källa.notat:
                field.källa.notat += f"; konvergens: {sorted(unique_sources)}"
            else:
                field.källa.notat = f"konvergens: {sorted(unique_sources)}"
        return field

    def needs_review(self, field: FieldValue) -> bool:
        """True om fältet behöver granskning (konfidens < tröskel, ADR-003)."""
        return field.needs_review

    def empty_field(self) -> FieldValue:
        """Tomt fält enligt JSON-schema (ADR-002: null, inte utelämnat)."""
        return FieldValue(värde=None, källa=None)
