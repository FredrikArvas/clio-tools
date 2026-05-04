"""
pipeline.py — ResearchPipeline: orchestrerar källorna och beräknar konfidens.

Fast pipeline-ordning: GEDCOM → Wikidata → Wikipedia → Libris (ADR-001).
Producerar ett PersonRecord (JSON-schema v1.0, ADR-007).
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from confidence import ConfidenceModel, FieldValue
from sources.gedcom import GedcomSource, GedcomPerson
from sources.wikidata import WikidataSource, WikidataResult
from sources.wikipedia import WikipediaSource, WikipediaResult
from sources.libris import LibrisSource, LibrisResult

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.0"


@dataclass
class PersonRecord:
    """
    Fullständig personpost i JSON-schema v1.0 format (ADR-007).
    Alla fält är FieldValue-instanser med värde + källreferens.
    """
    schema_version: str = "1.0"
    person_id: str = ""
    meta: dict = field(default_factory=dict)

    # identitet
    fornamn: FieldValue = field(default_factory=FieldValue)
    efternamn: FieldValue = field(default_factory=FieldValue)
    födelsedag: FieldValue = field(default_factory=FieldValue)
    födelseort: FieldValue = field(default_factory=FieldValue)
    dödsdag: FieldValue = field(default_factory=FieldValue)
    dödsort: FieldValue = field(default_factory=FieldValue)
    wikidata_id: FieldValue = field(default_factory=FieldValue)
    wikipedia_url: FieldValue = field(default_factory=FieldValue)
    levande: FieldValue = field(default_factory=FieldValue)

    # kontakt
    email: FieldValue = field(default_factory=FieldValue)
    telefon: FieldValue = field(default_factory=FieldValue)
    linkedin_url: FieldValue = field(default_factory=FieldValue)

    # profil
    yrke: FieldValue = field(default_factory=FieldValue)
    utbildning: FieldValue = field(default_factory=FieldValue)
    sammanfattning: FieldValue = field(default_factory=FieldValue)
    publikationer: list[dict] = field(default_factory=list)

    # övrigt
    sammanhang: list[str] = field(default_factory=list)
    relationer: list = field(default_factory=list)
    berikningsbehov: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialiserar till JSON-schema v1.0."""
        return {
            "schema_version": self.schema_version,
            "person_id": self.person_id,
            "meta": self.meta,
            "identitet": {
                "fornamn": self.fornamn.to_dict(),
                "efternamn": self.efternamn.to_dict(),
                "födelsedag": self.födelsedag.to_dict(),
                "födelseort": self.födelseort.to_dict(),
                "dödsdag": self.dödsdag.to_dict(),
                "dödsort": self.dödsort.to_dict(),
                "wikidata_id": self.wikidata_id.to_dict(),
                "wikipedia_url": self.wikipedia_url.to_dict(),
                "levande": self.levande.to_dict(),
            },
            "kontakt": {
                "email": self.email.to_dict(),
                "telefon": self.telefon.to_dict(),
                "linkedin_url": self.linkedin_url.to_dict(),
            },
            "profil": {
                "yrke": self.yrke.to_dict(),
                "utbildning": self.utbildning.to_dict(),
                "sammanfattning": self.sammanfattning.to_dict(),
                "publikationer": self.publikationer,
            },
            "sammanhang": self.sammanhang,
            "relationer": self.relationer,
            "berikningsbehov": self.berikningsbehov,
        }

    def fields_needing_review(self) -> list[tuple[str, FieldValue]]:
        """Returnerar lista av (fältnamn, FieldValue) som behöver granskning."""
        candidates = [
            ("fornamn", self.fornamn),
            ("efternamn", self.efternamn),
            ("födelsedag", self.födelsedag),
            ("födelseort", self.födelseort),
            ("dödsdag", self.dödsdag),
            ("dödsort", self.dödsort),
            ("wikidata_id", self.wikidata_id),
            ("wikipedia_url", self.wikipedia_url),
            ("yrke", self.yrke),
            ("sammanfattning", self.sammanfattning),
        ]
        return [(name, fv) for name, fv in candidates if fv.needs_review]


@dataclass
class PipelineResult:
    """Resultat från en pipeline-körning."""
    person_record: Optional[PersonRecord] = None
    needs_review: bool = False
    review_items: list[tuple[str, FieldValue]] = field(default_factory=list)
    wikidata_multiple_candidates: bool = False
    wikidata_candidates: list[dict] = field(default_factory=list)
    gdpr_flagged: bool = False
    errors: list[str] = field(default_factory=list)


class ResearchPipeline:
    """
    Orchestrerar insamling av persondata från GEDCOM → Wikidata → Wikipedia → Libris.

    Användning:
        pipeline = ResearchPipeline(gedcom_path=Path("fil.ged"))
        result = pipeline.run(gedcom_id="@I192@", syfte="guldboda-75")
    """

    def __init__(
        self,
        gedcom_path: Optional[Path] = None,
        wikidata_source: Optional[WikidataSource] = None,
        wikipedia_source: Optional[WikipediaSource] = None,
        libris_source: Optional[LibrisSource] = None,
    ):
        self.gedcom_path = gedcom_path
        self._gedcom: Optional[GedcomSource] = None
        self._wikidata = wikidata_source or WikidataSource()
        self._wikipedia = wikipedia_source or WikipediaSource()
        self._libris = libris_source or LibrisSource()
        self._cm = ConfidenceModel()

    def _get_gedcom(self) -> GedcomSource:
        if self._gedcom is None:
            if self.gedcom_path is None:
                raise ValueError("Ingen GEDCOM-fil angiven")
            self._gedcom = GedcomSource(self.gedcom_path)
        return self._gedcom

    def run(
        self,
        gedcom_id: str,
        syfte: str = "",
        person_id: str = "",
        levande_override: Optional[str] = None,  # "ja" | "nej" | "vet-ej" | None=auto
    ) -> PipelineResult:
        """
        Kör full pipeline för en person identifierad med GEDCOM-ID.

        levande_override: användarens svar på GDPR-frågan.
          "ja"    → GDPR-flagga, rensa kontaktuppgifter, hoppa över Wikipedia
          "nej"   → kör full pipeline utan GDPR-begränsningar
          "vet-ej"→ kör full pipeline men lägg till berikningsbehov-notat
          None    → auto-detektera via GEDCOM (asterisk = levande)

        Returns: PipelineResult med färdig PersonRecord och ev. granskningsbehov.
        """
        result = PipelineResult()

        # --- Steg 1: GEDCOM (ankarpunkt) ---
        gedcom_person = self._get_gedcom().get_person(gedcom_id)
        if gedcom_person is None:
            result.errors.append(f"Person {gedcom_id} hittades inte i GEDCOM-filen")
            return result

        record = self._build_from_gedcom(gedcom_person, gedcom_id, syfte, person_id)

        # Bestäm levande-status: användarens svar prioriteras över auto-detektering
        if levande_override == "ja":
            är_levande = True
        elif levande_override == "nej":
            är_levande = False
        elif levande_override == "vet-ej":
            är_levande = None  # okänt
        else:
            # Auto: asterisk i GEDCOM = levande (MyHeritage-konvention)
            är_levande = gedcom_person.levande and gedcom_person.har_asterisk

        # --- Steg 2: Wikidata ---
        self._enrich_from_wikidata(record, gedcom_person, result)

        # --- Steg 3: Wikipedia ---
        # Hoppa över Wikipedia om vi vet att personen är levande (GDPR, ADR-005)
        if är_levande is not True:
            self._enrich_from_wikipedia(record, result)

        # --- Steg 4: Libris ---
        self._enrich_from_libris(record, gedcom_person)

        # Konvergenscheck: om Wikidata och Wikipedia bekräftar samma födelsedag
        self._apply_convergence(record)

        # GDPR-hantering baserat på levande-status och syfte (rättslig grund)
        if är_levande is True:
            result.gdpr_flagged = True
            if syfte:
                # Syfte angivet = rättslig grund dokumenterad → kontaktuppgifter sparas
                record.berikningsbehov.append(
                    f"GDPR: levande person — rättslig grund: '{syfte}'"
                )
                logger.info("Levande person (%s) - GDPR-grund: '%s'", gedcom_id, syfte)
            else:
                # Inget syfte = skydda kontaktuppgifter (ADR-005)
                record.berikningsbehov.append(
                    "GDPR: levande person utan angivet syfte — kontaktuppgifter sparas ej"
                )
                record.email = self._cm.empty_field()
                record.telefon = self._cm.empty_field()
                logger.info("Levande person (%s) - inget syfte, kontaktuppgifter rensade", gedcom_id)
        elif är_levande is None:
            record.berikningsbehov.append(
                "Levande-status okänd — kontrollera om GDPR-begränsningar gäller"
            )

        # Saknar Wikipedia-sammanfattning för en historisk person → berikningsbehov
        if är_levande is False and not record.sammanfattning.värde:
            record.berikningsbehov.append("Wikipedia: ingen artikel hittad — manuell berikning kan behövas")

        result.person_record = record
        result.review_items = record.fields_needing_review()
        result.needs_review = (
            len(result.review_items) > 0
            or result.wikidata_multiple_candidates
            or bool(record.berikningsbehov)  # berikningsbehov → granskningskort
        )
        return result

    def _build_from_gedcom(
        self, person: GedcomPerson, gedcom_id: str, syfte: str, person_id: str
    ) -> PersonRecord:
        """Bygger ett PersonRecord från GEDCOM-data (grundkonfidens 0.95)."""
        cm = self._cm
        today = date.today().isoformat()

        record = PersonRecord(
            person_id=person_id or f"GED-{gedcom_id.strip('@')}",
            meta={
                "skapad": today,
                "skapad_av": "clio-research",
                "senast_uppdaterad": today,
                "status": "utkast",
                "pipeline_version": PIPELINE_VERSION,
                "syfte": syfte,
                "gedcom_id": gedcom_id,
            },
        )

        if syfte:
            record.sammanhang = [syfte]

        if person.fornamn:
            record.fornamn = cm.make_field(person.fornamn, "gedcom", hämtad=today)
        if person.efternamn:
            record.efternamn = cm.make_field(person.efternamn, "gedcom", hämtad=today)
        if person.fodelsedag:
            record.födelsedag = cm.make_field(person.fodelsedag, "gedcom", hämtad=today)
        if person.fodelseort:
            record.födelseort = cm.make_field(person.fodelseort, "gedcom", hämtad=today)
        if person.dodsdag:
            record.dödsdag = cm.make_field(person.dodsdag, "gedcom", hämtad=today)
        if person.dodsort:
            record.dödsort = cm.make_field(person.dodsort, "gedcom", hämtad=today)
        if person.levande is not None:
            record.levande = cm.make_field(person.levande, "gedcom", hämtad=today)
        if person.email:
            record.email = cm.make_field(person.email, "gedcom", hämtad=today)
        if person.telefon:
            record.telefon = cm.make_field(person.telefon, "gedcom", hämtad=today)

        return record

    def _enrich_from_wikidata(
        self, record: PersonRecord, person: GedcomPerson, result: PipelineResult
    ) -> None:
        """Berika med Wikidata. Hanterar multipla kandidater (ADR-004)."""
        today = date.today().isoformat()
        cm = self._cm

        year = person.fodelsedag[:4] if person.fodelsedag else None

        wd_result: WikidataResult = WikidataResult(found=False)

        if person.fornamn and person.efternamn and year:
            # Försök 1: fullständigt förnamn
            wd_result = self._wikidata.search_by_name_and_year(
                person.fornamn, person.efternamn, year
            )
            # Försök 2: bara första förnamnet (fallback för personer med mellannamn i GEDCOM)
            if not wd_result.found and not wd_result.multiple_candidates:
                first_name = person.fornamn.split()[0] if " " in person.fornamn else person.fornamn
                if first_name != person.fornamn:
                    wd_result = self._wikidata.search_by_name_and_year(
                        first_name, person.efternamn, year
                    )

        if wd_result.error:
            logger.warning("Wikidata-fel: %s", wd_result.error)
            result.errors.append(f"Wikidata: {wd_result.error}")
            return

        if wd_result.multiple_candidates:
            # ADR-004: skapa granskningskort
            result.wikidata_multiple_candidates = True
            result.wikidata_candidates = wd_result.candidates
            logger.info("Wikidata: %d kandidater - kraver granskning", len(wd_result.candidates))
            return

        if not wd_result.found:
            return

        # Spara Wikidata-fält
        wd_url = wd_result.wikidata_url
        if wd_result.wikidata_id:
            record.wikidata_id = cm.make_field(
                wd_result.wikidata_id, "wikidata", url=wd_url, hämtad=today
            )
        if wd_result.wikipedia_sv:
            record.wikipedia_url = cm.make_field(
                wd_result.wikipedia_sv, "wikidata", url=wd_url, hämtad=today
            )
        elif wd_result.wikipedia_en:
            record.wikipedia_url = cm.make_field(
                wd_result.wikipedia_en, "wikidata", url=wd_url, hämtad=today
            )
        if wd_result.fodelsedag and not record.födelsedag.värde:
            record.födelsedag = cm.make_field(
                wd_result.fodelsedag, "wikidata", url=wd_url, hämtad=today
            )
        if wd_result.fodelseort and not record.födelseort.värde:
            record.födelseort = cm.make_field(
                wd_result.fodelseort, "wikidata", url=wd_url, hämtad=today
            )
        if wd_result.dodsdag and not record.dödsdag.värde:
            record.dödsdag = cm.make_field(
                wd_result.dodsdag, "wikidata", url=wd_url, hämtad=today
            )
        if wd_result.yrke:
            record.yrke = cm.make_field(
                wd_result.yrke, "wikidata", url=wd_url, hämtad=today
            )

    def _enrich_from_wikipedia(self, record: PersonRecord, result: PipelineResult) -> None:
        """Berika med Wikipedia-sammanfattning."""
        today = date.today().isoformat()
        cm = self._cm

        wp_result: WikipediaResult
        if record.wikipedia_url.värde:
            wp_result = self._wikipedia.get_by_url(record.wikipedia_url.värde)
        elif record.fornamn.värde and record.efternamn.värde:
            wp_result = self._wikipedia.search(
                f"{record.fornamn.värde} {record.efternamn.värde}"
            )
        else:
            return

        if wp_result.error:
            logger.warning("Wikipedia-fel: %s", wp_result.error)
            return

        if not wp_result.found:
            return

        if wp_result.sammanfattning:
            record.sammanfattning = cm.make_field(
                wp_result.sammanfattning, "wikipedia",
                url=wp_result.url, hämtad=today
            )
        # Om wikipedia_url saknas, spara den vi hittade
        if not record.wikipedia_url.värde and wp_result.url:
            record.wikipedia_url = cm.make_field(
                wp_result.url, "wikipedia", url=wp_result.url, hämtad=today
            )

    def _enrich_from_libris(self, record: PersonRecord, person: GedcomPerson) -> None:
        """Berika med Libris-publikationer."""
        today = date.today().isoformat()

        if not person.efternamn:
            return

        lib_result: LibrisResult = self._libris.search_by_creator(
            person.efternamn, person.fornamn or ""
        )

        if lib_result.error:
            logger.warning("Libris-fel: %s", lib_result.error)
            return

        if not lib_result.found:
            return

        for pub in lib_result.publikationer:
            record.publikationer.append({
                "värde": {
                    "titel": pub.titel,
                    "roll": pub.roll,
                    "utgivare": pub.utgivare,
                    "år": pub.år,
                    "isbn": pub.isbn,
                },
                "källa": {
                    "typ": "libris",
                    "url": pub.libris_url,
                    "hämtad": today,
                    "konfidens": 0.65,
                    "notat": None,
                },
            })

    def _apply_convergence(self, record: PersonRecord) -> None:
        """
        Tillämpar konvergensregel om ≥2 oberoende källor bekräftar samma fält.
        (ADR-006: ≥2 oberoende källor → konfidens 0.85)
        """
        cm = self._cm
        has_wikidata = bool(record.wikidata_id.värde)

        # Födelsedag: GEDCOM + Wikidata bekräftar → boost
        if (
            record.födelsedag.värde
            and record.födelsedag.källa
            and record.födelsedag.källa.typ == "gedcom"
            and has_wikidata
        ):
            cm.apply_convergence(record.födelsedag, ["gedcom", "wikidata"])

        # Födelseort: GEDCOM + Wikidata bekräftar → boost
        if (
            record.födelseort.värde
            and record.födelseort.källa
            and record.födelseort.källa.typ == "gedcom"
            and has_wikidata
        ):
            cm.apply_convergence(record.födelseort, ["gedcom", "wikidata"])

        # Dödsdag: GEDCOM + Wikidata bekräftar → boost
        if (
            record.dödsdag.värde
            and record.dödsdag.källa
            and record.dödsdag.källa.typ == "gedcom"
            and has_wikidata
        ):
            cm.apply_convergence(record.dödsdag, ["gedcom", "wikidata"])

        # wikidata_id: om Wikidata hittade person och Wikipedia bekräftar (Wikipedia-URL finns) → boost
        if (
            has_wikidata
            and record.wikipedia_url.värde
        ):
            if record.wikidata_id.källa and record.wikidata_id.källa.typ == "wikidata":
                cm.apply_convergence(record.wikidata_id, ["wikidata", "wikipedia"])

        # wikipedia_url: om Wikidata och Wikipedia oberoende anger samma URL → boost
        if (
            record.wikipedia_url.värde
            and has_wikidata
        ):
            # Wikidata angav URL, Wikipedia bekräftade (search hittade samma artikel)
            if record.wikipedia_url.källa:
                cm.apply_convergence(record.wikipedia_url, ["wikidata", "wikipedia"])

        # sammanfattning: om Wikidata bekräftar personen och Wikipedia har sammanfattning → boost
        if (
            record.sammanfattning.värde
            and has_wikidata
            and record.sammanfattning.källa
            and record.sammanfattning.källa.typ == "wikipedia"
        ):
            cm.apply_convergence(record.sammanfattning, ["wikidata", "wikipedia"])
