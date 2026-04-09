"""
sources/gedcom.py — GedcomSource: läser GEDCOM-fil och extraherar persondata.

Stödjer MyHeritage-exporterade GEDCOM-filer (UTF-8 BOM, CRLF).
OBS: MyHeritage dubblerar @ i e-postadresser — normaliseras automatiskt.

Levande-detektering: levande=True om ingen DEAT-post finns.
har_asterisk=True om * förekommer i GIVN-fältet (MyHeritage-konvention).
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date
from typing import Optional


@dataclass
class GedcomPerson:
    """Rådata extraherad från ett INDI-block i GEDCOM-filen."""
    gedcom_id: str
    fornamn: Optional[str] = None
    efternamn: Optional[str] = None
    fodelsedag: Optional[str] = None       # "ÅÅÅÅ-MM-DD" om fullständigt, annars "ÅÅÅÅ" etc.
    fodelseort: Optional[str] = None
    dodsdag: Optional[str] = None
    dodsort: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None
    kön: Optional[str] = None             # "M" eller "F"
    har_asterisk: bool = False            # * i GIVN-fältet
    levande: bool = False                 # ingen DEAT-post
    rin: Optional[str] = None             # MyHeritage RIN (t.ex. MH:I192)
    raw_block: str = field(default="", repr=False)


def _normalize_email(raw: str) -> str:
    """Normaliserar MyHeritage-dubblerade @@ till @."""
    return raw.replace("@@", "@").strip()


def _parse_gedcom_date(date_str: str) -> Optional[str]:
    """
    Konverterar GEDCOM-datum till ISO-format.

    Hanterar:
      "27 JAN 1945" → "1945-01-27"
      "JAN 1945"    → "1945-01"
      "1945"        → "1945"
      "ABT 1945"    → "1945" (approximativ, notat kastas)
    """
    if not date_str:
        return None
    raw = date_str.strip().upper()
    # Ta bort kvalificerare som ABT, BEF, AFT, CAL, EST
    raw = re.sub(r'^(ABT|BEF|AFT|CAL|EST|CIR|CIRCA)\s+', '', raw)

    months = {
        "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
        "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
        "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
    }
    parts = raw.split()
    if len(parts) == 3:
        day, mon, year = parts
        m = months.get(mon)
        if m:
            return f"{year}-{m}-{day.zfill(2)}"
    if len(parts) == 2:
        mon, year = parts
        m = months.get(mon)
        if m:
            return f"{year}-{m}"
    if len(parts) == 1 and parts[0].isdigit() and len(parts[0]) == 4:
        return parts[0]
    return date_str.strip()  # fallback: returnera som-är


def _extract_tag_value(lines: list[str], level: int, tag: str) -> Optional[str]:
    """Hämtar värdet på första förekomst av 'level TAG value'."""
    prefix = f"{level} {tag} "
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def _extract_subblock(lines: list[str], level: int, tag: str) -> list[list[str]]:
    """
    Returnerar alla sub-block som börjar med 'level TAG'.
    Varje sub-block är en lista av rader på djupare nivåer.
    """
    result = []
    current: Optional[list[str]] = None
    parent_level = level
    for line in lines:
        stripped = line.strip()
        if re.match(rf'^{level} {tag}(\s|$)', stripped):
            if current is not None:
                result.append(current)
            current = [stripped]
        elif current is not None:
            # Kolla om vi är tillbaka på föräldranivå (avsluta sub-block)
            m = re.match(r'^(\d+) ', stripped)
            if m and int(m.group(1)) <= parent_level and not re.match(rf'^{level} {tag}(\s|$)', stripped):
                result.append(current)
                current = None
            else:
                current.append(stripped)
    if current is not None:
        result.append(current)
    return result


class GedcomSource:
    """
    Läser en GEDCOM-fil och extraherar personposter.

    Användning:
        gs = GedcomSource(Path("fil.ged"))
        person = gs.get_person("@I192@")
    """

    def __init__(self, gedcom_path: Path):
        self.path = Path(gedcom_path)
        self._blocks: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Läser och indexerar alla INDI-block efter GEDCOM-ID."""
        try:
            content = self.path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            content = self.path.read_text(encoding="latin-1")

        # Dela upp på INDI-poster (0 @Ixxx@ INDI)
        raw_blocks = re.split(r"(?=^0 @I)", content, flags=re.MULTILINE)
        for block in raw_blocks:
            m = re.match(r"^0 (@I\d+@) INDI", block.strip())
            if m:
                self._blocks[m.group(1)] = block

    def list_ids(self) -> list[str]:
        """Returnerar alla GEDCOM-IDs i filen."""
        return sorted(self._blocks.keys())

    def get_person(self, gedcom_id: str) -> Optional[GedcomPerson]:
        """
        Extraherar en GedcomPerson från GEDCOM-ID.

        Returnerar None om ID inte finns.
        """
        block = self._blocks.get(gedcom_id)
        if block is None:
            return None

        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        return self._parse_block(gedcom_id, lines, block)

    def _parse_block(self, gedcom_id: str, lines: list[str], raw_block: str) -> GedcomPerson:
        person = GedcomPerson(gedcom_id=gedcom_id, raw_block=raw_block)

        # Namn
        givn = _extract_tag_value(lines, 2, "GIVN")
        surn = _extract_tag_value(lines, 2, "SURN")

        # Fallback: parse från NAME-raden (1 NAME Förnamn /Efternamn/)
        if not givn or not surn:
            name_line = _extract_tag_value(lines, 1, "NAME")
            if name_line:
                m = re.match(r"^(.*?)\s*/([^/]*)/\s*$", name_line)
                if m:
                    if not givn:
                        givn = m.group(1).strip()
                    if not surn:
                        surn = m.group(2).strip()
                elif not givn:
                    givn = name_line.strip()

        # Normalisera: ta bort asterisk ur förnamn
        if givn:
            person.har_asterisk = "*" in givn
            person.fornamn = givn.replace("*", "").strip()
        if surn:
            person.efternamn = surn.replace("*", "").strip()

        # Kön
        person.kön = _extract_tag_value(lines, 1, "SEX")

        # Födelsedata
        birt_blocks = _extract_subblock(lines, 1, "BIRT")
        if birt_blocks:
            birt_lines = birt_blocks[0]
            raw_date = _extract_tag_value(birt_lines, 2, "DATE")
            if raw_date:
                person.fodelsedag = _parse_gedcom_date(raw_date)
            raw_plac = _extract_tag_value(birt_lines, 2, "PLAC")
            if raw_plac:
                person.fodelseort = raw_plac.strip()

        # Dödsdata
        deat_blocks = _extract_subblock(lines, 1, "DEAT")
        if deat_blocks:
            # Har DEAT-post → inte levande
            person.levande = False
            deat_lines = deat_blocks[0]
            raw_date = _extract_tag_value(deat_lines, 2, "DATE")
            if raw_date:
                person.dodsdag = _parse_gedcom_date(raw_date)
            raw_plac = _extract_tag_value(deat_lines, 2, "PLAC")
            if raw_plac:
                person.dodsort = raw_plac.strip()
        else:
            person.levande = True

        # E-post (kan ligga under RESI eller direkt som EMAIL)
        # Sök alla EMAIL-rader på nivå 2 (under RESI) eller nivå 1
        email_found = None
        for line in lines:
            if re.match(r"^\d+ EMAIL ", line):
                raw_email = line.split(" EMAIL ", 1)[1].strip()
                email_found = _normalize_email(raw_email)
                break
        person.email = email_found

        # Telefon
        telefon_found = None
        for line in lines:
            if re.match(r"^\d+ PHON ", line):
                telefon_found = line.split(" PHON ", 1)[1].strip()
                break
        person.telefon = telefon_found

        # RIN (MyHeritage-referensnummer)
        person.rin = _extract_tag_value(lines, 1, "RIN")

        return person

    def search_by_surname(self, surname: str) -> list[GedcomPerson]:
        """Returnerar alla personer med givet efternamn."""
        result = []
        for gedcom_id in self._blocks:
            p = self.get_person(gedcom_id)
            if p and p.efternamn and p.efternamn.lower() == surname.lower():
                result.append(p)
        return result
