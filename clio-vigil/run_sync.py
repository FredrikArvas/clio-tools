"""Backfill-sync: vigil_items → clio.vigil.item + clio.media.article"""
import sqlite3, logging, sys
from pathlib import Path

BASE_DIR = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "data" / "sync_backfill.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("sync")

from odoo_writer import get_odoo_env, sync_items_from_conn, sync_items_to_media

conn = sqlite3.connect(str(BASE_DIR / "data" / "vigil.db"))
conn.row_factory = sqlite3.Row

log.info("Ansluter till Odoo...")
odoo_env = get_odoo_env()
if not odoo_env:
    log.error("Kunde inte ansluta till Odoo")
    sys.exit(1)

log.info("=== sync_items_from_conn (clio.vigil.item) ===")
n = sync_items_from_conn(odoo_env, conn)
log.info("vigil.item: %d synkade", n)

log.info("=== sync_items_to_media (clio.media.article) ===")
m = sync_items_to_media(odoo_env, conn)
log.info("media.article: %d synkade", m)

conn.close()
log.info("Klar.")
