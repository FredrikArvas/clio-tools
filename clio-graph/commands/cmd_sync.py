"""cmd_sync.py — clio-graph sync [--dry-run]"""

from __future__ import annotations
import argparse


def add_parser(subparsers):
    p = subparsers.add_parser("sync", help="Synka Odoo → Neo4j")
    p.add_argument("--dry-run", action="store_true", help="Visa vad som skulle synkas utan att skriva")
    return p


def run(args: argparse.Namespace) -> int:
    from sync import run_sync
    noder, kanter = run_sync(dry_run=args.dry_run)
    tag = "[dry-run] " if args.dry_run else ""
    print(f"  {tag}Synkade {noder} noder, {kanter} kanter.")
    return 0
