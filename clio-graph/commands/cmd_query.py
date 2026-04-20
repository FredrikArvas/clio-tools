"""cmd_query.py — clio-graph query "<Cypher>" """

from __future__ import annotations
import argparse


def add_parser(subparsers):
    p = subparsers.add_parser("query", help="Kör en Cypher-fråga mot Neo4j")
    p.add_argument("cypher", help='Cypher-fråga, t.ex. "MATCH (p:Partner) RETURN p.name LIMIT 5"')
    return p


def run(args: argparse.Namespace) -> int:
    from graph_client import GraphClient
    with GraphClient() as g:
        with g.session() as s:
            result = s.run(args.cypher)
            rows = result.data()
    if not rows:
        print("  (inga träffar)")
    else:
        for row in rows:
            print(" ", row)
    return 0
