"""
clio_run_graph.py
Launcher för clio-graph — Odoo-nätverk → Neo4j-grafdatabas.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent

from clio_menu import (
    BackToMenu, _input,
    GRN, YEL, GRY, BLD, NRM,
    clear,
    menu_select, menu_pause,
)

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key


_CHOICES = [
    "1.  Synka Odoo → Neo4j         (skarpt)",
    "2.  Synka Odoo → Neo4j         (dry-run, skriver inget)",
    "3.  Statistik                  (noder och kanter i Neo4j)",
    "4.  Cypher-fråga               (fritt läge)",
]


def run_graph(tool: dict, state: dict) -> None:
    graph_run = ROOT / "clio-graph" / "run.py"

    while True:
        clear()
        print(f"\n{BLD}  clio-graph  —  Odoo-nätverk → Neo4j{NRM}")
        print(f"{'─' * 56}\n")
        choice = menu_select("Välj:", _CHOICES)
        if choice is None:
            return
        mode = choice.split(".")[0].strip()

        print(f"\n{'─' * 40}")
        start = datetime.now()

        try:
            if mode == "1":
                print("Synkar Odoo → Neo4j (skarpt)...")
                subprocess.run(
                    [sys.executable, str(graph_run), "sync"],
                    text=True, errors="replace")

            elif mode == "2":
                print("Synkar Odoo → Neo4j (dry-run)...")
                subprocess.run(
                    [sys.executable, str(graph_run), "sync", "--dry-run"],
                    text=True, errors="replace")

            elif mode == "3":
                subprocess.run(
                    [sys.executable, str(graph_run), "stats"],
                    text=True, errors="replace")

            elif mode == "4":
                from clio_menu import menu_text
                cypher = menu_text("  Cypher-fråga")
                if not cypher:
                    continue
                subprocess.run(
                    [sys.executable, str(graph_run), "query", cypher],
                    text=True, errors="replace")

        except KeyboardInterrupt:
            print("\n(Avbruten av användaren)")
        except Exception as e:
            print(f"\nFel: {e}")

        elapsed = (datetime.now() - start).seconds
        print(f"\n{'─' * 40}")
        print(t("run_done", s=elapsed))
        menu_pause()
