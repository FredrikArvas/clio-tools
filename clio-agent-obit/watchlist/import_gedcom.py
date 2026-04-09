"""
watchlist/import_gedcom.py — Proxy to clio-partnerdb import_gedcom.

All GEDCOM import logic now lives in clio-partnerdb/import_gedcom.py.
This file is kept for backwards compatibility with the clio menu and
direct invocation from clio-agent-obit/.

Usage (unchanged from Sprint 1):
    python watchlist/import_gedcom.py --gedcom FILE.ged --owner EMAIL [--ego NAME] [--depth 1-3]
    python watchlist/import_gedcom.py --gedcom FILE.ged --owner EMAIL --dry-run
    python watchlist/import_gedcom.py --gedcom FILE.ged --verify "Helena Arvas"
"""

from __future__ import annotations

import os
import sys

# Delegate to clio-partnerdb
_PARTNERDB = os.path.join(os.path.dirname(__file__), "..", "..", "clio-partnerdb")
sys.path.insert(0, _PARTNERDB)

from import_gedcom import main  # noqa: F401 — re-exported for menu integration


if __name__ == "__main__":
    main()
