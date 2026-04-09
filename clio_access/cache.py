"""
cache.py — generisk TTL-cache för clio-access

Enkel in-memory cache med konfigurerbar livslängd.
Trådsäker för single-process-användning (GIL räcker).
"""
import time
from typing import Any


class TTLCache:
    """In-memory cache med TTL per post."""

    def __init__(self, ttl: int = 900):
        """
        ttl : livslängd i sekunder (default 15 min)
        """
        self._ttl = ttl
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any:
        """Returnerar värdet om det finns och inte är utgånget, annars None."""
        if key in self._store:
            value, ts = self._store[key]
            if time.time() - ts < self._ttl:
                return value
            del self._store[key]
        return None

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.time())

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None
