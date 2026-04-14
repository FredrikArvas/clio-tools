"""
access.py — AccessManager för clio-access

Enda sanningskällan för access-kontroll i hela clio-tools-ekosystemet.

Användning:
    from clio_access import AccessManager

    am = AccessManager(
        notion_token="secret_...",
        matrix_page_id="33d67666...",
        admin_identities={"fredrik@arvas.se"},
    )

    am.get_level({"email": "ulrika@arvas.se"})          # → "write"
    am.get_level({"telegram_id": 123456789})             # → "admin"
    am.is_admin({"email": "fredrik@arvas.se"})           # → True
    am.get_accounts({"email": "ulrika@arvas.se"})        # → ["krut", "clio"]
"""
import logging
import os
from typing import Any

from .cache import TTLCache
from .notion_source import fetch_matrix

logger = logging.getLogger("clio-access")

# Giltiga nivåer i prioritetsordning
LEVELS = ("admin", "write", "coded", "whitelisted", "denied")

# Mapping nivå → roll (grovkornig)
_ROLE_MAP = {
    "admin":       "admin",
    "write":       "user",
    "coded":       "user",
    "whitelisted": "user",
    "denied":      "denied",
}


class AccessManager:
    """
    Hanterar behörighetskontroll mot Notion-matrisen.

    Identitet skickas som dict med ett eller flera av:
      {"email": "ulrika@arvas.se"}
      {"telegram_id": 123456789}
      {"email": "...", "telegram_id": ...}   ← båda används vid lookup
    """

    def __init__(
        self,
        notion_token: str,
        matrix_page_id: str,
        admin_identities: set | None = None,
        cache_ttl: int = 900,
    ):
        self._token = notion_token
        self._page_id = matrix_page_id
        self._admins: set[str] = {a.lower() for a in (admin_identities or set())}
        self._cache = TTLCache(ttl=cache_ttl)

    # ── Fabriksmetod för ConfigParser-baserade agenter ────────────────────────

    @classmethod
    def from_config(cls, config, section: str = "mail") -> "AccessManager":
        """
        Skapar en AccessManager från en ConfigParser-sektion.
        Förväntar sig:
          permissions_notion_page_id
          admin_addresses (kommaseparerade)
        och NOTION_API_KEY i miljön.
        """
        token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN", "")
        page_id = config.get(section, "permissions_notion_page_id", fallback="")
        raw_admins = config.get(section, "admin_addresses", fallback="")
        admins = {a.strip().lower() for a in raw_admins.split(",") if a.strip()}
        # Fallback
        if not admins:
            for key in ("notify_address", "notify_address_capgemini"):
                v = config.get(section, key, fallback="").lower().strip()
                if v:
                    admins.add(v)
        return cls(notion_token=token, matrix_page_id=page_id, admin_identities=admins)

    # ── Intern cache-hantering ────────────────────────────────────────────────

    def _matrix(self) -> dict:
        """Returnerar matrisen, hämtar från Notion om cachen är utgången."""
        cached = self._cache.get("matrix")
        if cached is not None:
            return cached
        data = fetch_matrix(self._page_id, self._token) if self._page_id else {"emails": {}, "telegram_ids": {}}
        self._cache.set("matrix", data)
        return data

    def _resolve(self, identity: dict) -> dict | None:
        """
        Slår upp identiteten i matrisen.
        Returnerar matris-posten eller None om ingen match.
        """
        matrix = self._matrix()

        # Försök e-post först
        email = identity.get("email", "").lower()
        if email and email in matrix["emails"]:
            return matrix["emails"][email]

        # Försök telegram_id
        tg_id = identity.get("telegram_id")
        if tg_id is not None:
            mapped_email = matrix["telegram_ids"].get(int(tg_id))
            if mapped_email and mapped_email in matrix["emails"]:
                return matrix["emails"][mapped_email]

        return None

    # ── Publik API ────────────────────────────────────────────────────────────

    def get_level(self, identity: dict, scope: str = "") -> str:
        """
        Returnerar behörighetsnivån för identiteten.
        Om scope anges (account_key), kontrolleras även konto-begränsning.

        → "admin" | "write" | "coded" | "whitelisted" | "denied"
        """
        # 1. Hard-coded admins (config)
        email = identity.get("email", "").lower()
        if email and email in self._admins:
            return "admin"

        # 2. Matris-lookup
        entry = self._resolve(identity)
        if not entry:
            return "denied"

        level = entry.get("level", "denied")
        allowed_accounts = entry.get("accounts", [])  # tom = alla konton

        # Konto-begränsning
        if scope and allowed_accounts and scope not in allowed_accounts:
            return "denied"

        return level if level in LEVELS else "denied"

    def get_role(self, identity: dict, scope: str = "") -> str:
        """
        Grovkornig roll — för enkel if/else i agenter som inte bryr sig om
        skillnaden mellan write och coded.

        → "admin" | "user" | "denied"
        """
        return _ROLE_MAP.get(self.get_level(identity, scope), "denied")

    def is_admin(self, identity: dict) -> bool:
        return self.get_level(identity) == "admin"

    def is_allowed(self, identity: dict, scope: str = "") -> bool:
        """Sant om nivån är något annat än 'denied'."""
        return self.get_level(identity, scope) != "denied"

    def get_accounts(self, identity: dict) -> list[str]:
        """
        Returnerar listan av tillåtna konton för identiteten.
        Tom lista = alla konton.
        """
        if self.is_admin(identity):
            return []  # admin = alla konton
        entry = self._resolve(identity)
        if not entry:
            return []
        return entry.get("accounts", [])

    def get_kodord_scope(self, identity: dict, scope: str = "") -> list[str] | None:
        """
        Returnerar listan av tillåtna kodord för identiteten.

        → None          om användaren är admin/write (inga begränsningar)
        → []            om scope är tom men behörighet finns (bör inte hända)
        → ["ssf", ...]  om specifika kodord är tillåtna
        → None          om kodord_scope är tom (= alla tillåtna)
        """
        level = self.get_level(identity, scope)
        if level in ("admin", "write"):
            return None  # inga begränsningar

        entry = self._resolve(identity)
        if not entry:
            return None

        scope_list = entry.get("kodord_scope", [])
        return scope_list if scope_list else None  # tom lista = alla

    def invalidate_cache(self) -> None:
        """Tvingar nästa anrop att hämta färsk data från Notion."""
        self._cache.invalidate("matrix")
