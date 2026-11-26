import sys, time
sys.path.insert(0, '/home/clioadmin/19.0/clio-tools/clio-vigil')

from orchestrator import init_db
from odoo_writer import get_odoo_env, sync_item, _item_to_vals, sync_items_to_media, SYNC_STATES

def ts():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

print(f"[{ts()}] Ansluter till Odoo (uap)...", flush=True)
env = get_odoo_env()
if not env:
    print("FAIL: Odoo-anslutning misslyckades")
    sys.exit(1)

conn = init_db()

# Synka ALLA states (inte bara SYNC_STATES) eftersom vi just rättat 72 items
rows = conn.execute("SELECT * FROM vigil_items ORDER BY id").fetchall()
total = len(rows)
print(f"[{ts()}] {total} items att synka (alla states)", flush=True)

synced = 0
errors = 0

for i, row in enumerate(rows, 1):
    ok = sync_item(env, row)
    if ok:
        synced += 1
    else:
        errors += 1

    if i % 1000 == 0 or i == total:
        print(f"[{ts()}] {i}/{total} — ok: {synced}, fel: {errors}", flush=True)

print(f"[{ts()}] vigil.item klar. Startar media.article-synk...", flush=True)
m = sync_items_to_media(env, conn)
print(f"[{ts()}] media.article: {m} synkade", flush=True)

conn.close()
print(f"[{ts()}] KLAR. vigil.item={synced}/{total}, media.article={m}, fel={errors}", flush=True)
