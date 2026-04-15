"""
notifier.py
SMTP-avsändare för clio-agent-job.
Konfigureras via config.yaml (icke-secrets) + .env (SMTP_PASSWORD).
AUTO_SEND direkt till kandidatens mail — inget approval-flöde.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

try:
    from dotenv import load_dotenv
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

_BASE_DIR = Path(__file__).parent
_ROOT_DIR = _BASE_DIR.parent
_CONFIG_YAML = _BASE_DIR / "config.yaml"


def _load_config() -> dict:
    if not _HAS_YAML:
        raise ImportError("PyYAML saknas — kör: pip install pyyaml")
    if not _CONFIG_YAML.exists():
        raise FileNotFoundError(f"config.yaml saknas: {_CONFIG_YAML}")
    with open(_CONFIG_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_env() -> None:
    if _HAS_DOTENV:
        load_dotenv(_ROOT_DIR / ".env")
        load_dotenv(_BASE_DIR / ".env", override=True)


def send_report(
    subject: str,
    body_text: str,
    body_html: str,
    to_addr: str,
    dry_run: bool = False,
) -> bool:
    """
    Skickar mailrapport till kandidatens adress.
    dry_run=True: skriver ut rapporten men skickar inget.
    Returnerar True vid lyckat skick (eller dry_run).
    """
    _load_env()
    cfg = _load_config()
    smtp_cfg = cfg.get("smtp", {})
    notify_cfg = cfg.get("notify", {})

    from_addr = notify_cfg.get("from_addr", smtp_cfg.get("user", "clio@arvas.international"))

    if dry_run:
        print("\n" + "═" * 60)
        print(f"[DRY-RUN] Mail som SKULLE skickas:")
        print(f"  Från:  {from_addr}")
        print(f"  Till:  {to_addr}")
        print(f"  Ämne:  {subject}")
        print("─" * 60)
        print(body_text)
        print("═" * 60 + "\n")
        return True

    host = smtp_cfg.get("host", "")
    port = int(smtp_cfg.get("port", 587))
    user = smtp_cfg.get("user", "")
    use_ssl = smtp_cfg.get("use_ssl", False)
    use_starttls = smtp_cfg.get("use_starttls", True)
    password_env = smtp_cfg.get("password_env", "SMTP_PASSWORD")
    password = os.environ.get(password_env, "")

    if not host or not user or not password:
        raise ValueError(
            f"Ofullständig SMTP-konfiguration — "
            f"kontrollera config.yaml och att {password_env} är satt i .env"
        )

    # Bygg MIME-meddelande
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                server.login(user, password)
                server.sendmail(from_addr, [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(host, port) as server:
                if use_starttls:
                    server.starttls(context=ssl.create_default_context())
                server.login(user, password)
                server.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except smtplib.SMTPException as e:
        raise RuntimeError(f"SMTP-fel: {e}") from e
