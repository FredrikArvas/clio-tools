"""
connection.py — OdooConnector: authenticated session wrapper for clio-odoo modules.

Reads credentials from .env (ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD).
Provides a thin facade over pyodoo-connect so callers never import it directly.

Usage:
    from clio_odoo import connect
    env = connect()
    Partner = env["res.partner"]
    rows = Partner.search_read([("name", "ilike", "Arvas")], ["name", "email"])
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def _load_env() -> None:
    """Load .env from clio-tools root (two levels up from this file)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return  # dotenv optional — env vars may already be set

    # Walk up to find .env: clio-odoo/../.env
    here = Path(__file__).resolve().parent
    for candidate in [here.parent / ".env", here / ".env"]:
        if candidate.exists():
            load_dotenv(candidate, override=False)
            return


class OdooConnector:
    """
    Authenticated Odoo session.

    Attributes:
        url      Odoo base URL
        db       Database name
        session  pyodoo_connect.OdooSession instance
    """

    def __init__(
        self,
        url: Optional[str] = None,
        db: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        _load_env()
        self.url      = url      or os.environ["ODOO_URL"]
        self.db       = db       or os.environ["ODOO_DB"]
        self.user     = user     or os.environ["ODOO_USER"]
        self._password = password or os.environ["ODOO_PASSWORD"]
        self.session  = self._authenticate()

    def _authenticate(self):
        try:
            from pyodoo_connect import OdooSession, connect_odoo
        except ImportError:
            sys.exit("pyodoo-connect saknas. Kör: pip install pyodoo-connect")

        session_id = connect_odoo(self.url, self.db, self.user, self._password)
        return OdooSession(url=self.url, session_id=session_id)

    def __getitem__(self, model_name: str):
        """env['res.partner'] — returns an OdooModel."""
        return self.session[model_name]

    def model(self, model_name: str):
        """Alias for env['model.name']."""
        return self.session[model_name]


def connect(
    url: Optional[str] = None,
    db: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> OdooConnector:
    """
    Convenience function — returns a ready-to-use OdooConnector.

    Example:
        env = connect()
        Partner = env["res.partner"]
    """
    return OdooConnector(url=url, db=db, user=user, password=password)
