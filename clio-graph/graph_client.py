"""
graph_client.py
Neo4j-anslutning via Bolt. Läser NEO4J_URI och NEO4J_PASSWORD från .env.

Usage:
    from graph_client import GraphClient
    with GraphClient() as g:
        with g.session() as s:
            result = s.run("MATCH (p:Partner) RETURN count(p) AS n")
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parent
    for candidate in [here.parent / ".env", here / ".env"]:
        if candidate.exists():
            load_dotenv(candidate, override=False)
            return


class GraphClient:
    def __init__(self, uri: Optional[str] = None, password: Optional[str] = None) -> None:
        _load_env()
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://192.168.1.189:7687")
        password = password or os.environ.get("NEO4J_PASSWORD", "")
        if not password:
            sys.exit("NEO4J_PASSWORD saknas i .env")
        try:
            from neo4j import GraphDatabase
        except ImportError:
            sys.exit("neo4j-drivrutinen saknas. Kör: pip install neo4j")
        self._driver = GraphDatabase.driver(self.uri, auth=("neo4j", password))

    def session(self):
        return self._driver.session()

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
