"""
sources/source_familjesidan_html.py — HTML-adapter för familjesidan.se

Familjesidan saknar publik RSS (verifierat 2026-04-08). Denna adapter
använder familjesidans publika sökgränssnitt /cases?... som returnerar
strukturerad HTML med en lista av annonser.

URL-mönstret: /cases?utf8=%E2%9C%93&client=familjesidan&newspapers=<id>&order_by=&direction=desc&view_type=advert

Selektorerna i CSS_DEFAULTS är ett första utkast. Verifiera mot live-sajt
med discover.py probe — om de bryter, uppdatera DEFAULTS eller åsidosätt
i sources.yaml.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from sources.source_html import HtmlListSource

# Default-selektorer verifierade mot live-sajt 2026-04-08 via discover.py probe.
# .result-row träffar 50 annons-rader, varje rad innehåller "Namn FödelseÅr DödsÅr".
# Familjesidan kan ändra detta — kör då discover.py probe igen för nya förslag.
CSS_DEFAULTS = {
    "list_selector": ".result-row",
    "name_selector": ".item-block, .item-value, h2, h3",
    "link_selector": "a",
    "summary_selector": ".item-value",
}


class FamiljesidanHtmlSource(HtmlListSource):
    """Hämtar dödsannonser från familjesidan.se via HTML-skrapning."""

    name = "familjesidan.se"

    def __init__(
        self,
        base_url: str = "https://www.familjesidan.se",
        newspapers: Optional[list[int]] = None,
        cities: Optional[list[str]] = None,
        list_selector: Optional[str] = None,
        name_selector: Optional[str] = None,
        link_selector: Optional[str] = None,
        summary_selector: Optional[str] = None,
        **kwargs,
    ):
        params = {
            "utf8": "✓",
            "client": "familjesidan",
            "search": "",
            "agencies": "",
            "newspapers": ",".join(str(n) for n in (newspapers or [])),
            "cities": ",".join(cities or []),
            "order_by": "",
            "direction": "desc",
            "view_type": "advert",
        }
        url = f"{base_url.rstrip('/')}/cases?{urlencode(params)}"

        super().__init__(
            url=url,
            list_selector=list_selector or CSS_DEFAULTS["list_selector"],
            name_selector=name_selector or CSS_DEFAULTS["name_selector"],
            link_selector=link_selector or CSS_DEFAULTS["link_selector"],
            summary_selector=summary_selector or CSS_DEFAULTS["summary_selector"],
            **kwargs,
        )
