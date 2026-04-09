"""
setup_credentials.py

Spara IMAP-inloggningsuppgifter i OS Credential Manager (keyring/DPAPI).
Konfiguration läses från clio.config [emailfetch].
Kör detta skript en gång per konto.

Användning:
    python setup_credentials.py
"""

import configparser
import getpass
import keyring
from pathlib import Path

_ROOT = Path(__file__).parent.parent  # clio-tools/

_DEFAULTS = {
    "service_name": "imap_three_com",
    "accounts":     "ordforande@guldboda.se,kassor@guldboda.se",
}


def _load_config() -> dict:
    cfg = configparser.ConfigParser()
    config_path = _ROOT / "clio.config"
    if config_path.exists():
        cfg.read(config_path, encoding="utf-8")

    def _get(key):
        try:
            v = cfg.get("emailfetch", key)
            return v.strip().strip('"').strip("'")
        except (configparser.NoSectionError, configparser.NoOptionError):
            return _DEFAULTS.get(key, "")

    accounts_raw = _get("accounts") or _DEFAULTS["accounts"]
    return {
        "service_name": _get("service_name") or _DEFAULTS["service_name"],
        "accounts":     [a.strip() for a in accounts_raw.split(",") if a.strip()],
    }


def save_credential(email: str, service_name: str) -> None:
    print(f"\nKonto: {email}")
    existing = keyring.get_password(service_name, email)
    if existing:
        overwrite = input("  Credentials finns redan. Skriv över? (j/n): ").strip().lower()
        if overwrite != "j":
            print("  Hoppar över.")
            return
    password = getpass.getpass(f"  Lösenord för {email}: ")
    keyring.set_password(service_name, email, password)
    print(f"  Sparat i Credential Manager.")


def verify_credentials(accounts: list, service_name: str) -> None:
    print("\n--- Verifiering ---")
    for email in accounts:
        pwd = keyring.get_password(service_name, email)
        status = "OK" if pwd else "SAKNAS"
        print(f"  {email}: {status}")


def main() -> None:
    cfg = _load_config()
    print("=== IMAP Credential Setup ===")
    print(f"Tjänst: {cfg['service_name']}")
    print(f"Backend: {keyring.get_keyring()}")
    print(f"Konton: {', '.join(cfg['accounts'])}")

    for email in cfg["accounts"]:
        save_credential(email, cfg["service_name"])

    verify_credentials(cfg["accounts"], cfg["service_name"])
    print("\nKlart! Kör imap_backup.py för att hämta mail.")


if __name__ == "__main__":
    main()
