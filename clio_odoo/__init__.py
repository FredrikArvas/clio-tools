"""clio-odoo — Shared Odoo connector library for all clio-odoo-* modules."""
from .connection import OdooConnector, connect

__all__ = ["OdooConnector", "connect"]
