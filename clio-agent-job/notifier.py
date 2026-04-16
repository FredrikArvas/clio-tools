"""
notifier.py
SMTP-avsändare för clio-agent-job.

Delar infrastruktur med clio-agent-mail:
  - Anropar clio-agent-mail/smtp_client.send_email()
  - Lösenord hämtas från clio-agent-mail/.env (IMAP_PASSWORD_CLIO)
  - Kopia sparas automatiskt i IMAP Skickat-mappen

Beroende: kräver att clio-agent-mail/ finns som syskonmapp i clio-tools/.
Notera: importerar bara smtp_client — inte main.py (undviker tunga handlers-importer).
"""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path

_BASE_DIR = Path(__file__).parent
_ROOT_DIR = _BASE_DIR.parent
_MAIL_DIR = _ROOT_DIR / "clio-agent-mail"

if not _MAIL_DIR.exists():
    raise ImportError(
        f"clio-agent-mail saknas på förväntad plats: {_MAIL_DIR}\n"
        "notifier.py kräver clio-agent-mail som syskonmodul i clio-tools/."
    )

if str(_MAIL_DIR) not in sys.path:
    sys.path.insert(0, str(_MAIL_DIR))

# Ladda clio-agent-mails .env så att IMAP_PASSWORD_CLIO finns i environ
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_MAIL_DIR / ".env", override=False)
except ImportError:
    pass

import smtp_client  # noqa: E402  (från clio-agent-mail via sys.path ovan)


def _load_mail_config() -> configparser.ConfigParser:
    """
    Minimal kopia av load_config() från clio-agent-mail/main.py.
    Läser clio.config och injicerar lösenord från miljövariabler.
    Importerar inte main.py (undviker hela handlers/notion-kedjan).
    """
    config = configparser.ConfigParser(interpolation=None)
    config_path = _MAIL_DIR / "clio.config"
    if not config_path.exists():
        raise FileNotFoundError(f"clio.config saknas: {config_path}")
    config.read(str(config_path), encoding="utf-8")

    if config.has_section("mail"):
        accounts_raw = config.get("mail", "accounts", fallback="clio,info")
        account_keys = [a.strip() for a in accounts_raw.split(",") if a.strip()]
        for key in set(account_keys + ["info"]):
            env_key = f"IMAP_PASSWORD_{key.upper()}"
            val = os.environ.get(env_key)
            if val:
                config.set("mail", f"imap_password_{key}", val)
    return config


def _admin_email() -> str:
    """Hämtar admin_email från clio-agent-job/config.yaml (Reply-To och CC)."""
    try:
        import yaml
        cfg_path = _BASE_DIR / "config.yaml"
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            return cfg.get("admin_email", "")
    except ImportError:
        pass
    return ""


def send_report(
    subject: str,
    body_text: str,
    body_html: str,
    to_addr: str,
    dry_run: bool = False,
) -> bool:
    """
    Skickar mailrapport till kandidatens adress via clio-agent-mails SMTP-infrastruktur.
    dry_run=True: skriver ut rapporten men skickar inget.
    Returnerar True vid lyckat skick (eller dry_run).
    """
    config = _load_mail_config()
    admin = _admin_email()

    smtp_client.send_email(
        config,
        from_account_key="clio",
        to_addr=to_addr,
        subject=subject,
        body=body_text,
        html_body=body_html,
        reply_to_addr=admin or None,
        dry_run=dry_run,
    )

    return True


def send_onboarding(
    subject: str,
    body_text: str,
    body_html: str,
    to_addr: str,
    dry_run: bool = False,
) -> bool:
    """Skickar onboarding-mail med CC till admin."""
    config = _load_mail_config()
    admin = _admin_email()

    smtp_client.send_email(
        config,
        from_account_key="clio",
        to_addr=to_addr,
        subject=subject,
        body=body_text,
        html_body=body_html,
        reply_to_addr=admin or None,
        cc_addrs=[admin] if admin and admin != to_addr else None,
        dry_run=dry_run,
    )

    return True
