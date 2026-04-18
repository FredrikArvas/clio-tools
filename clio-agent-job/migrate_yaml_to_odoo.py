"""
migrate_yaml_to_odoo.py
Läser YAML-profiler och skapar/uppdaterar clio.job.profile-poster i Odoo.

Kör på EliteDesk GPU:
    python migrate_yaml_to_odoo.py [--dry-run] [--profile richard.yaml]

Utan --profile körs alla YAML-filer i profiles/ (utom stubs med source: odoo).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BASE   = Path(__file__).parent
_ROOT   = _BASE.parent

for _p in [str(_ROOT), str(_ROOT / "clio-core")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    load_dotenv(_BASE / ".env")
except ImportError:
    pass

try:
    import yaml
except ImportError:
    sys.exit("PyYAML saknas — kör: pip install pyyaml")


def _lines_to_text(value) -> str:
    """Lista → radbruten text, eller sträng oförändrad."""
    if isinstance(value, list):
        return "\n".join(str(v).strip() for v in value if v)
    return str(value).strip() if value else ""


def migrate_profile(env, data: dict, dry_run: bool) -> None:
    name  = data.get("name", "").strip()
    email = data.get("email", "").strip()

    if not name or not email:
        print(f"  [HOPPAR ÖVER] Saknar name eller email: {data.get('name')}")
        return

    print(f"\n→ {name} ({email})")

    # --- Hitta eller skapa res.partner ---
    Partner = env["res.partner"]
    partners = Partner.search_read(
        [("email", "=", email), ("is_company", "=", False)],
        ["id", "name", "clio_job_watch", "clio_job_profile_ids"],
    )

    if partners:
        partner = partners[0]
        print(f"  Partner hittad: ID {partner['id']} ({partner['name']})")
    else:
        if dry_run:
            print(f"  [DRY-RUN] Skulle skapa partner: {name} <{email}>")
            partner = {"id": None, "clio_job_profile_ids": []}
        else:
            pid = Partner.create({"name": name, "email": email, "is_company": False})
            partner = {"id": pid, "clio_job_profile_ids": []}
            print(f"  Partner skapad: ID {pid}")

    # --- Sätt clio_job_watch = True ---
    if partner["id"] and not partner.get("clio_job_watch"):
        if not dry_run:
            Partner.write([partner["id"]], {"clio_job_watch": True})
        print(f"  clio_job_watch → True")

    # --- Bygg profildata ---
    profile_vals = {
        "report_email":    email,
        "role":            data.get("role", "") or "",
        "seniority":       data.get("seniority", "") or "",
        "geography":       data.get("geography", "") or "",
        "hybrid_ok":       bool(data.get("hybrid_ok", True)),
        "background":      _lines_to_text(data.get("background", [])),
        "education":       _lines_to_text(data.get("education", [])),
        "target_roles":    _lines_to_text(data.get("target_roles", [])),
        "signal_keywords": _lines_to_text(data.get("signal_keywords", [])),
    }

    Profile = env["clio.job.profile"]
    existing_ids = partner.get("clio_job_profile_ids") or []

    if existing_ids:
        # Uppdatera befintlig profil
        if dry_run:
            print(f"  [DRY-RUN] Skulle uppdatera profil ID {existing_ids[0]}")
        else:
            Profile.write([existing_ids[0]], profile_vals)
            print(f"  Profil uppdaterad (ID {existing_ids[0]})")
    else:
        # Skapa ny profil
        if partner["id"]:
            profile_vals["partner_id"] = partner["id"]
        if dry_run:
            print(f"  [DRY-RUN] Skulle skapa ny clio.job.profile")
        else:
            new_id = Profile.create(profile_vals)
            print(f"  Profil skapad (ID {new_id})")


def main():
    ap = argparse.ArgumentParser(description="Migrera YAML-profiler till Odoo clio.job.profile")
    ap.add_argument("--dry-run", action="store_true", help="Visa vad som skulle göras, utan att skriva")
    ap.add_argument("--profile", type=str, default=None, help="Specifik YAML-fil (t.ex. richard.yaml)")
    args = ap.parse_args()

    # Välj profiler
    profiles_dir = _BASE / "profiles"
    if args.profile:
        yaml_files = [profiles_dir / args.profile]
    else:
        yaml_files = sorted(profiles_dir.glob("*.yaml"))

    # Filtrera bort Odoo-stubbar
    to_migrate = []
    for f in yaml_files:
        with open(f, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            continue
        if data.get("source") == "odoo":
            print(f"[HOPPAR ÖVER] {f.name} — source: odoo (redan i Odoo)")
            continue
        to_migrate.append((f.name, data))

    if not to_migrate:
        print("Inga profiler att migrera.")
        return

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}Migrerar {len(to_migrate)} profil(er) till Odoo...\n")

    try:
        from clio_odoo import connect
        env = connect()
    except Exception as e:
        sys.exit(f"[FEL] Kunde inte ansluta till Odoo: {e}")

    for fname, data in to_migrate:
        print(f"[{fname}]")
        try:
            migrate_profile(env, data, dry_run=args.dry_run)
        except Exception as e:
            print(f"  [FEL] {e}")

    print("\nKlart.")


if __name__ == "__main__":
    main()
