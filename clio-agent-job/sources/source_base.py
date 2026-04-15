"""
source_base.py
Abstrakt basklass och dataklasser för clio-agent-job nyhetskällor.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Article:
    """Normaliserad nyhetsartikel från valfri källa."""
    url: str
    title: str
    source: str
    published: Optional[datetime] = None
    body_snippet: str = ""
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def article_id(self) -> str:
        """sha256 av URL — stabil, unik identifierare."""
        return hashlib.sha256(self.url.encode()).hexdigest()

    def published_str(self) -> str:
        if self.published:
            return self.published.strftime("%Y-%m-%d")
        return self.fetched_at.strftime("%Y-%m-%d")


class SourceError(Exception):
    """Kastas av källimplementationer vid nätverks- eller parsningsfel."""
    pass


class BaseSource(ABC):
    """Abstrakt basklass för alla nyhetskällor."""

    name: str = "okänd"

    @abstractmethod
    def fetch(self) -> list[Article]:
        """Hämtar artiklar. Kastar SourceError vid fel."""
        ...
