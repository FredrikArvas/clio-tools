"""
sources/source_html.py — Generisk HTML-listadapter

CSS-selektor-driven källa. Konfigureras helt via sources.yaml utan att
behöva en egen Python-fil. Konkreta källor (familjesidan, fonus) ärver
av denna och fyller bara i sajt-specifika selektorer.

Konfigurationsfält:
    url               (str, krävs)  Lista-URL att hämta
    list_selector     (str, krävs)  CSS-selector för varje annons-element
    name_selector     (str, krävs)  Selector inom listan — namnet
    link_selector     (str)         Selector för länken (default: 'a')
    summary_selector  (str)         Selector för annonstext (valfri)
    birth_year_selector (str)       Selector för födelseår (valfri)
    user_agent        (str)         HTTP User-Agent (default: clio-agent-obit/0.2)
    timeout           (int)         HTTP-timeout i sekunder (default: 20)
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    raise ImportError("requests saknas. Kör: pip install requests")

try:
    from bs4 import BeautifulSoup
except ImportError:
    raise ImportError("beautifulsoup4 saknas. Kör: pip install beautifulsoup4")

from matcher import Announcement
from sources.source_base import ObituarySource, SourceError
from sources.parsers import extract_birth_year, extract_death_year, extract_location, clean_name


DEFAULT_USER_AGENT = "clio-agent-obit/0.2 (+https://arvas.se)"


class HtmlListSource(ObituarySource):
    """
    Generisk källa som hämtar en HTML-sida och plockar ut annonser
    via CSS-selektorer.
    """

    name = "html"

    def __init__(
        self,
        url: str,
        list_selector: str,
        name_selector: str,
        link_selector: str = "a",
        summary_selector: Optional[str] = None,
        birth_year_selector: Optional[str] = None,
        detail_body_selector: Optional[str] = None,
        detail_image_selector: Optional[str] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: int = 20,
        **_unused,  # tolerera framtida fält i sources.yaml
    ):
        self.url = url
        self.list_selector = list_selector
        self.name_selector = name_selector
        self.link_selector = link_selector
        self.summary_selector = summary_selector
        self.birth_year_selector = birth_year_selector
        self.detail_body_selector = detail_body_selector
        self.detail_image_selector = detail_image_selector
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch(self) -> list[Announcement]:
        try:
            resp = requests.get(
                self.url,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise SourceError(f"Nätverksfel mot {self.url}: {e}") from e

        return self._parse(resp.text)

    def _parse(self, html: str) -> list[Announcement]:
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(self.list_selector)

        announcements: list[Announcement] = []
        for item in items:
            try:
                ann = self._parse_item(item)
                if ann:
                    announcements.append(ann)
            except Exception as e:
                print(f"[{self.name}] kunde inte parsa item: {e}")
        return announcements

    def _parse_item(self, item) -> Optional[Announcement]:
        name_el = item.select_one(self.name_selector)
        if not name_el:
            return None
        raw_title = name_el.get_text(" ", strip=True)
        if not raw_title:
            return None

        link_el = item.select_one(self.link_selector)
        href = ""
        if link_el and link_el.has_attr("href"):
            href = urljoin(self.url, link_el["href"])

        summary = ""
        if self.summary_selector:
            sum_el = item.select_one(self.summary_selector)
            if sum_el:
                summary = sum_el.get_text(" ", strip=True)

        full_text = f"{raw_title} {summary}"

        if self.birth_year_selector:
            by_el = item.select_one(self.birth_year_selector)
            if by_el:
                full_text = f"{by_el.get_text(' ', strip=True)} {full_text}"

        birth_year = extract_birth_year(full_text)
        death_year = extract_death_year(full_text)
        location = extract_location(full_text)

        ann_id = href or f"{self.name}:{raw_title}"

        return Announcement(
            id=ann_id,
            namn=clean_name(raw_title),
            fodelsear=birth_year,
            dodsar=death_year,
            hemort=location,
            url=href or self.url,
            publiceringsdatum="",
            raw_title=raw_title,
            source_name=self.name,
        )

    def fetch_detail(self, url: str) -> dict:
        """
        Hämtar detaljsidan för en annons och extraherar brödtext + tidningsbild.

        Returnerar dict med nycklarna:
            body_html  (str)  — annonstext som HTML-fragment
            image_url  (str)  — URL till bild, tom sträng om ingen hittad

        Selektorer konfigureras via detail_body_selector / detail_image_selector
        i sources.yaml. Generiska fallbacks provar vanliga element om inga
        specifika selektorer är satta.
        """
        result = {"body_html": "", "image_url": ""}
        if not url:
            return result
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException:
            return result

        soup = BeautifulSoup(resp.text, "html.parser")

        # ── Brödtext ──────────────────────────────────────────────────────────
        body_el = None
        if self.detail_body_selector:
            body_el = soup.select_one(self.detail_body_selector)
        if not body_el:
            for sel in [
                ".case-content", ".advert-text", ".advert-body",
                ".memorial-text", ".obit-text", "article", "main",
            ]:
                body_el = soup.select_one(sel)
                if body_el:
                    break
        if body_el:
            result["body_html"] = str(body_el)
        else:
            paras = soup.find_all("p")
            html_parts = [str(p) for p in paras if p.get_text(strip=True)]
            result["body_html"] = "\n".join(html_parts[:20])

        # ── Bild ──────────────────────────────────────────────────────────────
        image_el = None
        if self.detail_image_selector:
            image_el = soup.select_one(self.detail_image_selector)
        if not image_el:
            for sel in [
                ".advert-image img", ".case-image img",
                ".memorial-photo img", "img.portrait", ".obituary-image img",
                ".notice-image img",
            ]:
                image_el = soup.select_one(sel)
                if image_el:
                    break
        if image_el:
            src = image_el.get("src") or image_el.get("data-src") or ""
            if src and not src.startswith("data:"):
                result["image_url"] = urljoin(url, src)

        return result
