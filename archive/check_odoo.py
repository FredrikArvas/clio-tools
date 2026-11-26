import os, sys
from pathlib import Path
from dotenv import load_dotenv
from collections import Counter
load_dotenv(Path("clio-vigil/.env"))
sys.path.insert(0, ".")
from clio_odoo import connect

env = connect(
    url=os.environ.get("VIGIL_ODOO_URL","https://uap.arvas.international"),
    db=os.environ.get("VIGIL_ODOO_DB","uap"),
)
Item = env["clio.vigil.item"]

total = Item.search_read([("source_name","=","Multiverse 5D")], ["id","state"])
states = Counter(r["state"] for r in total)
print("Multiverse 5D totalt:", len(total), "poster")
print("Per state:", dict(states))

q = Item.search_read(
    [("source_name","=","Multiverse 5D"),("state","=","queued")],
    ["id","title","state","priority_score"],
)
print("\nQueued:", len(q))
for r in q:
    print("  id=%d prio=%.0f %s" % (r["id"], r["priority_score"], (r["title"] or "")[:60]))
