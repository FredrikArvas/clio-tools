"""
odoo_sync.py — Odoo XML-RPC sync-funktion för events_db

Exporterar make_odoo_sync_fn(config) som returnerar en callable
kompatibel med events_db.log_event(odoo_sync_fn=...).

Designval:
  - Använder stdlib xmlrpc.client — inga extra beroenden
  - Anropar clio.event.log.sync_from_sqlite() via execute_kw
  - Autentisering: url + db + username + password från config [odoo]-sektion
  - Fel propagerar — events_db worker hanterar retry med backoff
  - make_odoo_sync_fn returnerar None om Odoo-config saknas (sync inaktiverad)

Config-sektion (clio.config):
  [odoo]
  url      = https://odoo.arvas.international
  db       = aiab-db
  username = clio@arvas.international
  password = <API-nyckel från Odoo>
"""

import logging
import xmlrpc.client
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def make_odoo_sync_fn(config) -> Optional[Callable[[dict], None]]:
    """
    Bygger och returnerar en sync-funktion för Odoo.

    Returnerar None om [odoo]-sektionen saknas eller är ofullständig
    — detta inaktiverar Odoo-synk utan fel.

    Anropas en gång vid start, t.ex. i main.py.
    """
    try:
        url      = config.get("odoo", "url",      fallback="").strip()
        db       = config.get("odoo", "db",       fallback="").strip()
        username = config.get("odoo", "username", fallback="").strip()
        password = config.get("odoo", "password", fallback="").strip()
    except Exception:
        return None

    if not all([url, db, username, password]):
        logger.debug("Odoo-synk inaktiverad — [odoo]-config ofullständig")
        return None

    # Verifiera anslutning och autentisering en gång vid start
    try:
        uid = _authenticate(url, db, username, password)
    except Exception as exc:
        logger.warning("Odoo-autentisering misslyckades — synk inaktiverad: %s", exc)
        return None

    logger.info("Odoo-synk aktiv: %s (uid=%s, db=%s)", url, uid, db)

    def _sync_fn(row: dict) -> None:
        """
        Synkar en events.db-rad till Odoo via sync_from_sqlite().

        row: dict från sqlite3.Row — nycklar matchar events.db-schema.
        Fel propagerar till events_db worker (retry med backoff).
        """
        models_proxy = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
        models_proxy.execute_kw(
            db, uid, password,
            "clio.event.log", "sync_from_sqlite",
            [dict(row)],
        )
        logger.debug("Odoo-synk OK: sqlite_id=%s utfall=%s", row.get("id"), row.get("utfall"))

    return _sync_fn


def _authenticate(url: str, db: str, username: str, password: str) -> int:
    """
    Autentiserar mot Odoo och returnerar uid.
    Kastar Exception vid fel.
    """
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, username, password, {})
    if not uid:
        raise ValueError(f"Odoo nekade inloggning för {username}@{db}")
    return uid


def check_odoo_connection(config) -> dict:
    """
    Testar Odoo-anslutningen och returnerar en statusdict.
    Används av diagnostik/health-check.

    Returnerar:
      {'ok': True,  'uid': 42,   'url': '...', 'db': '...'}
      {'ok': False, 'error': '...', 'url': '...', 'db': '...'}
    """
    url      = config.get("odoo", "url",      fallback="")
    db       = config.get("odoo", "db",       fallback="")
    username = config.get("odoo", "username", fallback="")
    password = config.get("odoo", "password", fallback="")

    try:
        uid = _authenticate(url, db, username, password)
        return {"ok": True, "uid": uid, "url": url, "db": db}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url, "db": db}
