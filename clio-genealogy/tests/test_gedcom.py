"""
test_gedcom.py — Enhetstester för GedcomSource.

OBS: Testar mot den riktiga GEDCOM-filen. Kräver att filen finns på angiven sökväg.
Rätt GEDCOM-ID för Dag Arvas är @I294@ (inte @I379@ som handover-dokumentet anger).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from sources.gedcom import GedcomSource, GedcomPerson, _parse_gedcom_date, _normalize_email

GEDCOM_FILE = Path(
    "C:/Users/fredr/Documents/Dropbox/ulrika-fredrik/släktforskning/"
    "släkten Fredrik arvas/släktträdsfiler/"
    "ChristersFredriksSammanslagna - 2010-09-20.ged"
)


@pytest.fixture(scope="module")
def gs():
    if not GEDCOM_FILE.exists():
        pytest.skip(f"GEDCOM-fil saknas: {GEDCOM_FILE}")
    return GedcomSource(GEDCOM_FILE)


# --- Enhetstester för hjälpfunktioner ---

class TestParseDateHelper:
    def test_full_date(self):
        assert _parse_gedcom_date("27 JAN 1945") == "1945-01-27"

    def test_month_year(self):
        assert _parse_gedcom_date("JAN 1945") == "1945-01"

    def test_year_only(self):
        assert _parse_gedcom_date("1945") == "1945"

    def test_approximate_date(self):
        result = _parse_gedcom_date("ABT 1932")
        assert "1932" in result

    def test_none_returns_none(self):
        assert _parse_gedcom_date(None) is None

    def test_empty_returns_none(self):
        assert _parse_gedcom_date("") is None

    def test_all_months(self):
        months = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
        for i, mon in enumerate(months, 1):
            result = _parse_gedcom_date(f"15 {mon} 2000")
            assert result == f"2000-{i:02d}-15", f"Misslyckades för {mon}"


class TestNormalizeEmail:
    def test_double_at_normalized(self):
        assert _normalize_email("b.arvas@@modernamuseet.se") == "b.arvas@modernamuseet.se"

    def test_normal_email_unchanged(self):
        assert _normalize_email("test@example.com") == "test@example.com"

    def test_strips_whitespace(self):
        assert _normalize_email("  test@example.com  ") == "test@example.com"


# --- Integrationstester mot riktiga GEDCOM-filen ---

class TestBirgittaArvas:
    """@I192@ — Birgitta Arvas"""

    def test_person_found(self, gs):
        p = gs.get_person("@I192@")
        assert p is not None

    def test_fornamn(self, gs):
        p = gs.get_person("@I192@")
        assert p.fornamn == "Birgitta"

    def test_efternamn(self, gs):
        p = gs.get_person("@I192@")
        assert p.efternamn == "Arvas"

    def test_fodelsedag(self, gs):
        p = gs.get_person("@I192@")
        assert p.fodelsedag == "1945-01-27"

    def test_fodelseort(self, gs):
        p = gs.get_person("@I192@")
        assert p.fodelseort is not None
        assert "Stockholm" in p.fodelseort or "Kungsholmen" in p.fodelseort

    def test_email_normalized(self, gs):
        p = gs.get_person("@I192@")
        assert p.email is not None
        assert "@@" not in p.email
        assert "@" in p.email
        assert p.email == "b.arvas@modernamuseet.se"

    def test_levande(self, gs):
        # Birgitta har ingen DEAT-post → levande
        p = gs.get_person("@I192@")
        assert p.levande is True

    def test_ingen_asterisk(self, gs):
        p = gs.get_person("@I192@")
        assert p.har_asterisk is False


class TestDagArvas:
    """@I294@ — Dag Gustaf Christer Arvas (korrekt ID, handover-dokument anger felaktigt @I379@)"""

    def test_person_found(self, gs):
        p = gs.get_person("@I294@")
        assert p is not None

    def test_fornamn(self, gs):
        p = gs.get_person("@I294@")
        # "Dag*" → "Dag" efter normalisering
        assert "Dag" in p.fornamn

    def test_efternamn(self, gs):
        p = gs.get_person("@I294@")
        assert p.efternamn == "Arvas"

    def test_fodelsedag(self, gs):
        p = gs.get_person("@I294@")
        assert p.fodelsedag == "1913-09-22"

    def test_fodelseort(self, gs):
        p = gs.get_person("@I294@")
        assert p.fodelseort is not None
        assert "Arvidsjaur" in p.fodelseort

    def test_dodsdag(self, gs):
        p = gs.get_person("@I294@")
        assert p.dodsdag is not None
        assert "2004" in p.dodsdag

    def test_dodsort(self, gs):
        p = gs.get_person("@I294@")
        assert p.dodsort is not None
        assert "Farsta" in p.dodsort

    def test_ej_levande(self, gs):
        p = gs.get_person("@I294@")
        assert p.levande is False


class TestFredrikArvas:
    """@I411@ — Fredrik Johan Gustaf Arvas (levande)"""

    def test_person_found(self, gs):
        p = gs.get_person("@I411@")
        assert p is not None

    def test_fornamn(self, gs):
        p = gs.get_person("@I411@")
        assert "Fredrik" in p.fornamn

    def test_efternamn(self, gs):
        p = gs.get_person("@I411@")
        assert p.efternamn == "Arvas"

    def test_har_asterisk(self, gs):
        p = gs.get_person("@I411@")
        assert p.har_asterisk is True

    def test_levande(self, gs):
        p = gs.get_person("@I411@")
        assert p.levande is True

    def test_fodelsedag(self, gs):
        p = gs.get_person("@I411@")
        assert p.fodelsedag == "1969-02-10"


class TestMissingPerson:
    def test_nonexistent_id_returns_none(self, gs):
        p = gs.get_person("@I99999@")
        assert p is None

    def test_list_ids_returns_list(self, gs):
        ids = gs.list_ids()
        assert isinstance(ids, list)
        assert "@I192@" in ids
        assert "@I294@" in ids
        assert "@I411@" in ids


class TestSearchBySurname:
    def test_search_arvas(self, gs):
        results = gs.search_by_surname("Arvas")
        assert len(results) > 0
        for p in results:
            assert p.efternamn == "Arvas"

    def test_search_case_insensitive(self, gs):
        results_upper = gs.search_by_surname("ARVAS")
        results_lower = gs.search_by_surname("arvas")
        assert len(results_upper) == len(results_lower)
