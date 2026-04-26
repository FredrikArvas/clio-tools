"""
sources/source_fonus.py — HTML-adapter för minnessidor.fonus.se

Sveriges största begravningsbyrå. Saknar RSS (verifierat 2026-04-08).
Använder den publika listan av minnessidor som primär källa.

Selektorerna är defaults — verifiera med discover.py probe och
åsidosätt vid behov i sources.yaml.
"""

from __future__ import annotations

from typing import Optional

from sources.source_html import HtmlListSource

# Default-selektorer verifierade mot live-sajt 2026-04-26.
# .item träffar 50 minnessida-rader. Varje .item har .user_text med h4 (namn)
# och span (födelseår - dödsdatum hemort), samt en länk till minnessidan.
CSS_DEFAULTS = {
    "list_selector":  ".item",
    "name_selector":  ".user_text h4",
    "link_selector":  ".user_text a",
    "summary_selector": ".user_text span",
}


class FonusSource(HtmlListSource):
    """Hämtar dödsannonser från minnessidor.fonus.se."""

    name = "minnessidor.fonus.se"

    def __init__(
        self,
        url: str = "https://minnessidor.fonus.se/",
        list_selector: Optional[str] = None,
        name_selector: Optional[str] = None,
        link_selector: Optional[str] = None,
        summary_selector: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            url=url,
            list_selector=list_selector or CSS_DEFAULTS["list_selector"],
            name_selector=name_selector or CSS_DEFAULTS["name_selector"],
            link_selector=link_selector or CSS_DEFAULTS["link_selector"],
            summary_selector=summary_selector or CSS_DEFAULTS["summary_selector"],
            **kwargs,
        )
