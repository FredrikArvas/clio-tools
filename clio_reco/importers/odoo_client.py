"""Delad XML-RPC-anslutning till Odoo. Läs credentials från .env."""
import os
import xmlrpc.client
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

ODOO_URL = os.environ["ODOO_URL"]
ODOO_DB = os.environ["ODOO_DB"]
ODOO_USER = os.environ["ODOO_USER"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]


def connect():
    """Returnerar (uid, models-proxy) redo för execute_kw-anrop."""
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise RuntimeError(f"Inloggning misslyckades: {ODOO_USER}@{ODOO_URL} ({ODOO_DB})")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models


def ensure_genre(models, uid, name: str) -> int:
    """Hämtar eller skapar en clio.reco.genre och returnerar dess ID."""
    existing = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "clio.reco.genre", "search",
        [[["name", "=", name]]],
    )
    if existing:
        return existing[0]
    return models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "clio.reco.genre", "create",
        [{"name": name}],
    )
