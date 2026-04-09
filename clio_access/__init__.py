"""
clio-access — delat behörighetspaket för clio-tools-ekosystemet

Publik API:
    from clio_access import AccessManager

    am = AccessManager(notion_token="...", matrix_page_id="...", admin_identities={...})
    am = AccessManager.from_config(config)   # ConfigParser-variant

    am.get_level({"email": "..."})           # → "admin|write|coded|whitelisted|denied"
    am.get_role({"email": "..."})            # → "admin|user|denied"
    am.is_admin({"email": "..."})            # → bool
    am.is_allowed({"email": "..."})          # → bool
    am.get_accounts({"email": "..."})        # → list[str]
"""
from .access import AccessManager

__all__ = ["AccessManager"]
__version__ = "1.0.0"
