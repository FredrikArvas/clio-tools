"""migrate.py — Läs Notion CSV-export och returnera normaliserade datastrukturer."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Svenska månadsnamn → nummer
_SV_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4,
    "maj": 5, "juni": 6, "juli": 7, "augusti": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}


def _parse_sv_date(s: str) -> date | None:
    """Parsa svenskt datumformat: '4 mars 2026' eller ISO '2026-03-04'."""
    if not s:
        return None
    s = s.strip()
    # ISO-format
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # Svenskt format: "4 mars 2026"
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", s)
    if m:
        day, month_sv, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = _SV_MONTHS.get(month_sv)
        if month:
            return date(year, month, day)
    return None


def _extract_name(notion_link: str) -> str:
    """Extrahera text från 'Namn (https://www.notion.so/...)' → 'Namn'."""
    if not notion_link:
        return ""
    notion_link = notion_link.strip()
    m = re.match(r"^(.+?)\s*\(https?://", notion_link)
    if m:
        return m.group(1).strip()
    return notion_link


def _parse_enum(value: str) -> str:
    """'3 - Physical Evidence' → '3', 'A - Denial' → 'A'."""
    if not value:
        return ""
    return value.split(" - ")[0].strip()


def _parse_multi_link(cell: str) -> list[str]:
    """Parsa kommaseparerad lista av Notion-links → lista av namn."""
    if not cell:
        return []
    parts = re.split(r",(?=\s*[^,]*(?:\(https?://|\s*$))", cell)
    return [_extract_name(p) for p in parts if p.strip()]


def _find_csv_in_zip(zip_path: Path, keyword: str) -> bytes | None:
    """
    Hitta och läs första CSV som matchar keyword i ett zip-arkiv.
    Hanterar Notion-format: zip → inner-zip → CSV.
    """
    def _search_zip(zf: zipfile.ZipFile) -> bytes | None:
        for name in zf.namelist():
            # Direkt CSV-träff
            if keyword.lower() in name.lower() and name.lower().endswith(".csv"):
                return zf.read(name)
        # Leta i inbäddade zip-filer (Notion-format)
        for name in zf.namelist():
            if name.lower().endswith(".zip"):
                inner_data = zf.read(name)
                try:
                    with zipfile.ZipFile(io.BytesIO(inner_data)) as inner_zf:
                        result = _search_zip(inner_zf)
                        if result is not None:
                            return result
                except zipfile.BadZipFile:
                    pass
        return None

    with zipfile.ZipFile(zip_path, "r") as zf:
        return _search_zip(zf)


def _read_csv_bytes(data: bytes) -> list[dict]:
    """Läs CSV-bytes (UTF-8 med BOM) till lista av dict."""
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _find_zip(data_path: Path, keyword: str) -> Path | None:
    """Hitta första zip-fil vars namn innehåller keyword."""
    for p in data_path.rglob("*.zip"):
        if keyword.lower() in p.name.lower():
            return p
    return None


def load_sources(data_path: Path) -> list[dict]:
    """Läs Sources 2 *.csv → lista av normaliserade uap.source-dicts."""
    zip_path = _find_zip(data_path, "Sources 2")
    if not zip_path:
        print(f"[VARNING] Hittade inte 'Sources 2' zip i {data_path}")
        return []

    raw = _find_csv_in_zip(zip_path, "Sources")
    if not raw:
        return []

    rows = _read_csv_bytes(raw)
    result = []
    for r in rows:
        source_type_raw = r.get("Source_Type", "").lower()
        type_map = {
            "book": "book", "documentary": "documentary", "article": "article",
            "archive": "archive", "web": "web", "journalism": "journalism",
        }
        tier_raw = r.get("Tier", "").lower().replace(" ", "_")
        tier_map = {"tier_1": "tier_1", "tier_2": "tier_2", "tier_3": "tier_3"}

        published = _parse_sv_date(r.get("Published_Date", ""))
        result.append({
            "source_id":      r.get("SourceID", "").strip(),
            "name":           r.get("Name", "").strip(),
            "source_type":    type_map.get(source_type_raw, "other"),
            "tier":           tier_map.get(tier_raw, False),
            "url":            r.get("userDefined:URL", r.get("Archive_URL", "")).strip() or False,
            "published_date": str(published) if published else False,
            "language":       r.get("Language", "").strip() or False,
        })
    return [r for r in result if r["source_id"]]


def load_witnesses(data_path: Path) -> list[dict]:
    """Läs Witnesses *.csv → lista av normaliserade uap.witness-dicts."""
    zip_path = _find_zip(data_path, "NHI")
    if not zip_path:
        print(f"[VARNING] Hittade inte NHI-zip i {data_path}")
        return []

    raw = _find_csv_in_zip(zip_path, "Witnesses")
    if not raw:
        return []

    rows = _read_csv_bytes(raw)
    result = []
    for r in rows:
        wtype = r.get("Witness_Type", "").lower()
        type_map = {
            "military": "military", "civilian": "civilian", "pilot": "pilot",
            "researcher": "researcher", "official": "official",
        }
        cred_raw = r.get("Credibility", "").lower().replace(" ", "_")
        cred_map = {"tier_1": "tier_1", "tier_2": "tier_2", "tier_3": "tier_3"}

        result.append({
            "name":        r.get("Name", "").strip(),
            "witness_type": type_map.get(wtype, "other"),
            "credibility": cred_map.get(cred_raw, False),
            "status":      r.get("Status", "").strip() or False,
            "url":         r.get("URL", "").strip() or False,
            "language":    r.get("Language", "").strip() or False,
        })
    return [r for r in result if r["name"]]


def load_encounters(data_path: Path) -> list[dict]:
    """
    Läs Incidents 2 *.csv → lista av encounter-dicts.
    Varje dict innehåller nyckeln '_source_names' och '_witness_names'
    för att resolva relationer i migrationsskriptet.
    """
    zip_path = _find_zip(data_path, "Incidents 2")
    if not zip_path:
        # Fallback: leta i Incidents.zip
        zip_path = _find_zip(data_path, "Incidents")
        if not zip_path:
            print(f"[VARNING] Hittade inte 'Incidents' zip i {data_path}")
            return []

    raw = _find_csv_in_zip(zip_path, "Incidents")
    if not raw:
        return []

    rows = _read_csv_bytes(raw)

    enc_class_map = {
        "1": "1", "2": "2", "3": "3", "4": "4",
    }
    disc_map = {"1": "1", "2": "2", "3": "3", "4": "4", "5": "5"}
    off_map  = {"A": "A", "B": "B", "C": "C", "D": "D", "E": "E"}
    status_map = {
        "pending review": "pending",
        "verified":       "verified",
        "archived":       "archived",
    }
    lang_map = {
        "english": "en", "swedish": "sv", "portuguese": "pt",
        "spanish": "es", "french": "fr", "german": "de", "japanese": "ja",
    }

    result = []
    for r in rows:
        enc_class_raw = _parse_enum(r.get("Encounter_Classification", ""))
        disc_raw      = _parse_enum(r.get("Discourse_Level", ""))
        off_raw       = _parse_enum(r.get("Official_Response", ""))
        status_raw    = r.get("Status", "").strip().lower()
        lang_raw      = r.get("Language_Original", "").strip().lower()

        date_str = r.get("date:Accessed_Date:start", r.get("Accessed_Date", "")).strip()
        date_obs = _parse_sv_date(date_str)

        source_names  = _parse_multi_link(r.get("Sources", ""))
        # Witnesses är indirekt via sources; vi lagrar source_names för nu
        # Om det finns en separat witness-kolumn använder vi den
        witness_names = _parse_multi_link(r.get("Witnesses", ""))

        result.append({
            "encounter_id":          r.get("IncidentTextID", "").strip(),
            "encounter_guid":        r.get("IncidentGUID", "").strip() or False,
            "date_observed":         str(datetime.combine(date_obs, datetime.min.time())) if date_obs else False,
            "location":              r.get("Location", "").strip() or False,
            "title_en":              r.get("Title_EN", "").strip() or False,
            "title_original":        r.get("Title_Original", "").strip() or False,
            "description_en":        r.get("Description_EN", "").strip() or False,
            "description_sv":        r.get("Description_SV", "").strip() or False,
            "description_original":  r.get("Description_Original", "").strip() or False,
            "language_original":     lang_map.get(lang_raw, "other") if lang_raw else False,
            "encounter_class":       enc_class_map.get(enc_class_raw, False),
            "discourse_level":       disc_map.get(disc_raw, False),
            "official_response":     off_map.get(off_raw, False),
            "status":                status_map.get(status_raw, "pending"),
            "research_notes":        r.get("Research_Notes", "").strip() or False,
            # Interna nycklar för relationsresolvning
            "_source_names":         source_names,
            "_witness_names":        witness_names,
            "_country_name":         _extract_name(r.get("Country_Linked", r.get("Country_Input", ""))),
        })
    return [r for r in result if r["encounter_id"]]


def load_verifications(data_path: Path) -> list[dict]:
    """Läs Verification Log 2 *.csv → lista av uap.verification-dicts."""
    zip_path = _find_zip(data_path, "VerificationLog")
    if not zip_path:
        zip_path = _find_zip(data_path, "Verification Log 2")
        if not zip_path:
            print(f"[VARNING] Hittade inte Verification-zip i {data_path}")
            return []

    raw = _find_csv_in_zip(zip_path, "Verification")
    if not raw:
        return []

    rows = _read_csv_bytes(raw)
    status_map = {
        "verified": "verified", "pending review": "pending", "rejected": "rejected",
    }
    result = []
    for r in rows:
        change_date = _parse_sv_date(r.get("Change_Date", ""))
        encounter_name = _extract_name(r.get("Incident", ""))
        status_raw = r.get("Verification_Status", "").strip().lower()

        name = r.get("Name", "").strip()
        # Incident-kolumnen är tom i exporten — extrahera encounter_id från Name
        # Mönster: "SWE_PPXL_0001 - Beskrivning" eller "NOR_CLA_030 - Fix"
        if not encounter_name:
            m_enc = re.match(r"^([A-Z]{2,4}_[A-Z]{2,6}_\d+)", name)
            encounter_name = m_enc.group(1) if m_enc else ""

        result.append({
            "name":                  name,
            "change_date":           str(change_date) if change_date else False,
            "changed_by":            r.get("Changed_By", "").strip() or False,
            "field_name":            r.get("Field_Name", "").strip() or False,
            "original_value":        r.get("Original_Value", "").strip() or False,
            "updated_value":         r.get("Updated_Value", "").strip() or False,
            "reason":                r.get("Reason_for_Change", "").strip() or False,
            "source_link":           r.get("Source_Link", "").strip() or False,
            "verification_status":   status_map.get(status_raw, "pending"),
            "_encounter_id":         encounter_name,
        })
    return [r for r in result if r["name"]]
