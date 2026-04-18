"""check_deps.py — Verify that clio-odoo dependencies are met."""
import sys

REQUIRED = [
    ("pyodoo_connect", "pyodoo-connect"),
    ("dotenv",         "python-dotenv"),
]

ok = True
for module, pkg in REQUIRED:
    try:
        __import__(module)
        print(f"  ✅ {pkg}")
    except ImportError:
        print(f"  ❌ {pkg}  →  pip install {pkg}")
        ok = False

# Check env vars
import os
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path, override=False)

missing_vars = []
for var in ["ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD"]:
    if not os.environ.get(var):
        missing_vars.append(var)

if missing_vars:
    print(f"  ❌ Saknade env-variabler i .env: {', '.join(missing_vars)}")
    ok = False
else:
    print(f"  ✅ .env: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD")

if ok:
    print("\nclio-odoo: alla beroenden OK")
else:
    print("\nclio-odoo: beroenden saknas (se ovan)")
    sys.exit(1)
