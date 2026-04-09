"""
sources/source_base.py — Abstrakt basklass för dödsannonskällor

Alla källor implementerar detta interface. Det gör det enkelt att lägga
till nya källor (begravning.se, lokaltidningar) utan att ändra run.py.

CC: Om vi lägger till en källa, kopiera source_familjesidan.py som mall.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from matcher import Announcement


class ObituarySource(ABC):
    """Basklass för en källa av dödsannonser."""

    name: str = "okänd"  # Överskrivs av subklassen

    @abstractmethod
    def fetch(self) -> list[Announcement]:
        """
        Hämtar nya annonser från källan.
        Returnerar en lista av Announcement-objekt.
        Kastar SourceError vid nätverksfel eller parse-fel.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


class SourceError(Exception):
    """Fel vid hämtning eller parsning från en källa."""
    pass
