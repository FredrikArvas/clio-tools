"""
notion_writer.py — NotionWriter: skriver personposter och granskningskort till Notion.

Kräver NOTION_TOKEN i miljön (ADR-008).
Skriver aldrig halvfärdig post — avbryt och logga vid API-fel (ADR-008).
"""

from __future__ import annotations
import json
import logging
from datetime import date
from typing import Optional

from notion_client import Client
from notion_client.errors import APIResponseError

from confidence import FieldValue
from pipeline import PersonRecord, PipelineResult

logger = logging.getLogger(__name__)

# Notion-konfiguration (från SPEC.md)
NOTION_PERSONREGISTER_DB = "ce2b62fe-1574-4386-9fb1-e7f226e6e34b"
NOTION_CONTEXT_CARD_ID = "33967666-d98a-8179-b3f1-c217e1421628"


def _text_block(text: str) -> dict:
    """Skapar ett paragraph-textblock för Notion."""
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}]
        },
    }


def _code_block(content: str, language: str = "json") -> dict:
    """Skapar ett kodblock för Notion."""
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": content[:2000]}}],
            "language": language,
        },
    }


def _heading_block(text: str, level: int = 2) -> dict:
    """Skapar en rubrik (heading_1, heading_2, heading_3)."""
    h = f"heading_{min(max(level, 1), 3)}"
    return {
        "object": "block",
        "type": h,
        h: {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _table_row(cells: list[str]) -> dict:
    return {
        "type": "table_row",
        "table_row": {
            "cells": [[{"type": "text", "text": {"content": c}}] for c in cells]
        },
    }


class NotionWriter:
    """
    Skriver PersonRecord till Notion Personregister och skapar granskningskort.

    Användning:
        nw = NotionWriter(notion_token="secret_xxx")
        page_id = nw.write_person(pipeline_result)
        review_id = nw.create_review_card(pipeline_result)
    """

    def __init__(self, notion_token: str):
        self._client = Client(auth=notion_token)

    def write_person(self, result: PipelineResult, dry_run: bool = False) -> Optional[str]:
        """
        Sparar PersonRecord till Notion Personregister.

        Returns: Notion page ID, eller None vid dry_run eller fel.
        Avbryt och logga vid API-fel — skriv aldrig halvfärdig post (ADR-008).
        """
        record = result.person_record
        if record is None:
            logger.error("Inget PersonRecord att spara")
            return None

        namn = f"{record.fornamn.värde or ''} {record.efternamn.värde or ''}".strip()
        källor = self._collect_source_types(record)
        status = "Utkast"

        properties = {
            "Namn": {
                "title": [{"text": {"content": namn}}]
            },
        }
        if record.sammanhang:
            properties["Sammanhang"] = {
                "multi_select": [{"name": s} for s in record.sammanhang]
            }
        if källor:
            properties["Källor"] = {
                "multi_select": [{"name": k} for k in sorted(källor)]
            }
        properties["Status"] = {"select": {"name": status}}

        # JSON-innehåll (dela upp i bitar om > 2000 tecken)
        json_str = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
        chunks = [json_str[i:i+2000] for i in range(0, len(json_str), 2000)]
        children = [_heading_block("Persondata (JSON)", level=2)]
        for chunk in chunks:
            children.append(_code_block(chunk))

        if dry_run:
            logger.info("[dry-run] Skulle sparat '%s' till Personregistret", namn)
            return None

        try:
            page = self._client.pages.create(
                parent={"database_id": NOTION_PERSONREGISTER_DB},
                properties=properties,
                children=children,
            )
            page_id = page["id"]
            logger.info("Sparad personpost: %s (%s)", namn, page_id)
            return page_id
        except APIResponseError as exc:
            logger.error("Notion API-fel vid sparning av '%s': %s", namn, exc)
            return None

    def create_review_card(self, result: PipelineResult, dry_run: bool = False) -> Optional[str]:
        """
        Skapar granskningskort i Notion under Context Card.

        Triggas när konfidens < 0.70 eller Wikidata ger multipla kandidater (ADR-003, ADR-004).
        Returns: Notion page ID, eller None vid dry_run eller fel.
        """
        record = result.person_record
        namn = ""
        syfte = ""
        if record:
            namn = f"{record.fornamn.värde or ''} {record.efternamn.värde or ''}".strip()
            syfte = record.meta.get("syfte", "") if record.meta else ""

        today = date.today().isoformat()
        title = f"Granskning: {namn or 'Okänd person'} — {today}"

        children: list[dict] = [
            _heading_block("Granskningsbehov", level=2),
        ]

        # Syfte / rättslig grund
        if syfte:
            children.append(_heading_block("Syfte (rättslig grund)", level=3))
            children.append(_text_block(f"Angett syfte: {syfte}"))

        # Insamlad data — sammanfattning
        if record:
            children.append(_heading_block("Insamlad data", level=3))
            fält_rad = []
            if record.fornamn.värde:
                fält_rad.append(f"Förnamn: {record.fornamn.värde}")
            if record.efternamn.värde:
                fält_rad.append(f"Efternamn: {record.efternamn.värde}")
            if record.födelsedag.värde:
                fält_rad.append(f"Födelsedag: {record.födelsedag.värde} (konf={record.födelsedag.konfidens:.2f})")
            if record.födelseort.värde:
                fält_rad.append(f"Födelseort: {record.födelseort.värde} (konf={record.födelseort.konfidens:.2f})")
            if record.dödsdag.värde:
                fält_rad.append(f"Dödsdag: {record.dödsdag.värde} (konf={record.dödsdag.konfidens:.2f})")
            if record.dödsort.värde:
                fält_rad.append(f"Dödsort: {record.dödsort.värde}")
            if record.wikidata_id.värde:
                fält_rad.append(f"Wikidata: {record.wikidata_id.värde}")
            if record.wikipedia_url.värde:
                fält_rad.append(f"Wikipedia: {record.wikipedia_url.värde}")
            if record.email.värde:
                fält_rad.append(f"E-post: {record.email.värde}")
            if record.telefon.värde:
                fält_rad.append(f"Telefon: {record.telefon.värde}")
            if record.yrke.värde:
                fält_rad.append(f"Yrke: {record.yrke.värde}")
            if record.sammanfattning.värde:
                fält_rad.append(f"Sammanfattning: {record.sammanfattning.värde[:200]}...")
            if record.publikationer:
                fält_rad.append(f"Libris-publikationer: {len(record.publikationer)} st")
            for rad in fält_rad:
                children.append(_text_block(rad))

        # Berikningsbehov
        if record and record.berikningsbehov:
            children.append(_heading_block("Berikningsbehov", level=3))
            for behov in record.berikningsbehov:
                children.append(_text_block(f"• {behov}"))

        # Fält med låg konfidens
        if result.review_items:
            children.append(_heading_block("Fält med låg konfidens (< 0.70)", level=3))
            for fältnamn, fv in result.review_items:
                konfidens = fv.konfidens
                källtyp = fv.källa.typ if fv.källa else "–"
                källurl = fv.källa.url if fv.källa else "–"
                rad = f"{fältnamn}: {fv.värde!r} (konf={konfidens:.2f}, källa={källtyp})"
                if källurl:
                    rad += f" [{källurl}]"
                children.append(_text_block(rad))

        # Wikidata-kandidater (ADR-004)
        if result.wikidata_multiple_candidates:
            children.append(_heading_block("Wikidata — flera kandidater (välj en)", level=3))
            for i, candidate in enumerate(result.wikidata_candidates, 1):
                info = (
                    f"{i}. {candidate.get('label', '?')} "
                    f"({candidate.get('wikidata_id', '?')}) "
                    f"— född {candidate.get('fodelsedag', '?')} "
                    f"i {candidate.get('fodelseort', '?')}"
                )
                children.append(_text_block(info))
                if candidate.get("wikidata_url"):
                    children.append(_text_block(f"   URL: {candidate['wikidata_url']}"))

        # GDPR-flagga
        if result.gdpr_flagged:
            children.append(_heading_block("GDPR", level=3))
            if syfte:
                children.append(_text_block(
                    f"Levande person. Rättslig grund dokumenterad: '{syfte}'. "
                    "Kontaktuppgifter sparas under detta syfte."
                ))
            else:
                children.append(_text_block(
                    "Levande person utan angivet syfte — kontaktuppgifter har rensats. "
                    "Ange syfte (rättslig grund) för att spara kontaktuppgifter."
                ))

        # Ev. fel
        if result.errors:
            children.append(_heading_block("Fel under insamling", level=3))
            for err in result.errors:
                children.append(_text_block(f"• {err}"))

        # Fritextfält för korrigeringar
        children.append(_heading_block("Korrigeringar", level=3))
        children.append(_text_block("(fyll i här)"))

        # Granskningskort är en vanlig undersida (inte i databas) → bara title tillåtet
        properties = {
            "title": [{"text": {"content": title}}],
        }

        if dry_run:
            logger.info("[dry-run] Skulle skapat granskningskort: %s", title)
            return None

        try:
            page = self._client.pages.create(
                parent={"page_id": NOTION_CONTEXT_CARD_ID},
                properties=properties,
                children=children,
            )
            page_id = page["id"]
            logger.info("Granskningskort skapat: %s (%s)", title, page_id)
            return page_id
        except APIResponseError as exc:
            logger.error("Notion API-fel vid skapande av granskningskort: %s", exc)
            return None

    def list_pending_reviews(self) -> list[dict]:
        """Hämtar väntande poster från två källor:
        1. Granskningskort (child pages under Context Card med titel 'Granskning:…')
        2. Personregistret — poster med Status = 'Utkast'
        """
        pages = []

        # Källa 1: granskningskort under Context Card
        try:
            response = self._client.blocks.children.list(block_id=NOTION_CONTEXT_CARD_ID)
            for block in response.get("results", []):
                if block.get("type") == "child_page":
                    title = block.get("child_page", {}).get("title", "")
                    if title.startswith("Granskning:"):
                        pages.append({
                            "id": block["id"],
                            "title": title,
                            "source": "granskning",
                        })
        except APIResponseError as exc:
            logger.error("Kunde inte hämta granskningskort: %s", exc)

        # Källa 2: personregistret — Status = Utkast
        # notion-client v3 döpte om databases.query → data_sources.query
        try:
            response = self._client.data_sources.query(
                NOTION_PERSONREGISTER_DB,
                filter={"property": "Status", "select": {"equals": "Utkast"}},
            )
            seen_ids = {p["id"] for p in pages}
            for page in response.get("results", []):
                page_id = page["id"]
                if page_id in seen_ids:
                    continue
                namn_parts = page.get("properties", {}).get("Namn", {}).get("title", [])
                namn = "".join(t.get("plain_text", "") for t in namn_parts) or "Okänd"
                pages.append({
                    "id": page_id,
                    "title": f"Utkast: {namn}",
                    "source": "register",
                })
        except APIResponseError as exc:
            logger.error("Kunde inte söka i personregistret: %s", exc)

        return pages

    def _collect_source_types(self, record: PersonRecord) -> set[str]:
        """Samlar alla unika källtyper som används i posten."""
        sources: set[str] = set()
        fields = [
            record.fornamn, record.efternamn, record.födelsedag, record.födelseort,
            record.dödsdag, record.dödsort, record.wikidata_id, record.wikipedia_url,
            record.levande, record.email, record.telefon, record.yrke,
            record.utbildning, record.sammanfattning,
        ]
        for fv in fields:
            if fv.källa and fv.värde is not None:
                sources.add(fv.källa.typ)
        for pub in record.publikationer:
            if pub.get("källa", {}).get("typ"):
                sources.add(pub["källa"]["typ"])
        return sources
