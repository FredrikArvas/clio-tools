#!/usr/bin/env python3
"""
queue_military.py
Boostar Multiverse 5D-avsnitt med vittnesmål + militär bakgrund till transkriptionskön.
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path("clio-vigil/.env"))
sys.path.insert(0, ".")
from clio_odoo import connect

env = connect(
    url=os.environ.get("VIGIL_ODOO_URL", "https://uap.arvas.international"),
    db=os.environ.get("VIGIL_ODOO_DB", "uap"),
)

# Militärrelaterade bakgrundstaggar
Bg = env["clio.podcast.background"]
mil_recs = Bg.search_read(
    [("code", "in", ["military", "military_program", "intelligence"])],
    ["id", "code", "name"],
)
mil_ids = [r["id"] for r in mil_recs]
print("Militärtaggar:", [(r["code"], r["name"]) for r in mil_recs])

# Matchande avsnitt: vittnesmål + militär
Item = env["clio.vigil.item"]
matches = Item.search_read(
    [
        ("source_name", "=", "Multiverse 5D"),
        ("podcast_format", "=", "testimony"),
        ("podcast_background_ids", "in", mil_ids),
    ],
    ["id", "title", "language", "podcast_witness_score", "state"],
    order="podcast_witness_score desc",
)

print(f"\nMatchande avsnitt: {len(matches)}")
for m in matches:
    score = m["podcast_witness_score"]
    title = (m["title"] or "")[:70]
    state = m["state"]
    lang  = m["language"] or "?"
    print(f"  [{score:.1f}] [{lang}] {title}  ({state})")

if not matches:
    print("Inga avsnitt matchar — kontrollera taggdata.")
    sys.exit(0)

# Sätt state=queued + hög prioritet baserat på vittnespoäng
ids = [m["id"] for m in matches]
for m in matches:
    new_prio = 500.0 + float(m["podcast_witness_score"] or 0) * 10
    Item.write([m["id"]], {
        "state":          "queued",
        "priority_score": new_prio,
    })

print(f"\n✅ {len(ids)} avsnitt satta till queued (prio 510–600).")
