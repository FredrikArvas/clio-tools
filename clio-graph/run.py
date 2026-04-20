"""
run.py — clio-graph entry-point (agent-ready).

Kommandon:
  sync  [--dry-run]   Synka Odoo → Neo4j
  stats               Visa antal noder/kanter i Neo4j
  query "<Cypher>"    Kör en Cypher-fråga

Exempel:
  python clio-graph/run.py sync --dry-run
  python clio-graph/run.py stats
  python clio-graph/run.py query "MATCH (a)-[r]->(b) RETURN a.name, type(r), b.name LIMIT 10"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from commands import cmd_sync, cmd_stats, cmd_query


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clio-graph",
        description="Clio Graph — synkroniserar Odoo-nätverk till Neo4j.",
    )
    sub = parser.add_subparsers(dest="command", metavar="KOMMANDO")
    sub.required = True
    cmd_sync.add_parser(sub)
    cmd_stats.add_parser(sub)
    cmd_query.add_parser(sub)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "sync":  cmd_sync.run,
        "stats": cmd_stats.run,
        "query": cmd_query.run,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
