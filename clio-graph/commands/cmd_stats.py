"""cmd_stats.py — clio-graph stats"""

from __future__ import annotations
import argparse


def add_parser(subparsers):
    p = subparsers.add_parser("stats", help="Visa antal noder och kanter i Neo4j")
    return p


def run(args: argparse.Namespace) -> int:
    from graph_client import GraphClient
    with GraphClient() as g:
        with g.session() as s:
            noder   = s.run("MATCH (p:Partner) RETURN count(p) AS n").single()["n"]
            kanter  = s.run("MATCH ()-[r:RELATION]->() RETURN count(r) AS n").single()["n"]
    print(f"  Noder (Partner): {noder}")
    print(f"  Kanter (RELATION): {kanter}")
    return 0
