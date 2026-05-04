"""status_mailer.py — Wrapper runt clio-agent-mail/smtp_client.py för statusmail."""

from __future__ import annotations

import configparser
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_MAIL_DIR = Path(__file__).parent.parent / "clio-agent-mail"
_ROOT_DIR = Path(__file__).parent.parent
_CONFIG_PATH = _MAIL_DIR / "clio.config"
_ENV_PATH = _ROOT_DIR / ".env"

SENDER = "clio"
RECIPIENT = "fredrik@arvas.se"


def _get_config() -> configparser.ConfigParser | None:
    if not _MAIL_DIR.exists():
        logger.warning("clio-agent-mail saknas: %s", _MAIL_DIR)
        return None

    sys.path.insert(0, str(_MAIL_DIR))

    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH)
        if (_MAIL_DIR / ".env").exists():
            load_dotenv(_MAIL_DIR / ".env", override=True)
    except ImportError:
        pass

    config = configparser.ConfigParser(interpolation=None)
    config.read(str(_CONFIG_PATH), encoding="utf-8")

    try:
        accounts = config.get("mail", "accounts").split(",")
        for key in accounts:
            key = key.strip()
            env_val = os.environ.get(f"IMAP_PASSWORD_{key.upper()}")
            if env_val:
                config.set("mail", f"imap_password_{key}", env_val)
    except (configparser.NoSectionError, configparser.NoOptionError):
        pass

    return config


def send_phase_complete(run_id: str, phase: int, label: str,
                        source_count: int, relevant_count: int,
                        question: str = "") -> None:
    """Statusmail vid fasavslut."""
    q_line = f"\nFråga: {question}" if question else ""
    subject = f"[clio-research] Fas {phase} ({label}) klar{' — ' + question[:50] if question else ''}"
    body = (
        f"Fas {phase}: {label}{q_line}\n\n"
        f"Källor insamlade totalt: {source_count}\n"
        f"Nya i fas {phase}: {relevant_count}\n\n"
        f"Körning: {run_id}\n"
    )
    _send(subject, body)


def send_anomaly(run_id: str, phase: int, message: str, question: str = "") -> None:
    """Anomalimail vid oväntat fynd."""
    q_line = f" | {question[:50]}" if question else ""
    subject = f"[clio-research] Anomali fas {phase}{q_line}"
    body = f"Fas {phase}{' (' + question + ')' if question else ''}:\n\n{message}\n\nKörning: {run_id}\n"
    _send(subject, body)


def send_final_report(run_id: str, report_path: Path, question: str = "") -> None:
    """Slutleverans med rapport som bilaga."""
    q_line = question[:60] if question else run_id
    subject = f"[clio-research] Rapport klar — {q_line}"
    body = (
        f"Evidensrapport klar.\n\n"
        f"Fråga: {question or '(okänd)'}\n"
        f"Rapport: {report_path}\n"
        f"Körning: {run_id}\n"
    )
    attachments = [str(report_path)] if report_path and report_path.exists() else []
    _send(subject, body, attachments=attachments)


def _send(subject: str, body: str, attachments: list | None = None) -> None:
    config = _get_config()
    if config is None:
        logger.warning("Mail ej skickat (config saknas): %s", subject)
        return

    try:
        from smtp_client import send_email
        send_email(
            config=config,
            from_account_key=SENDER,
            to_addr=RECIPIENT,
            subject=subject,
            body=body,
            attachments=attachments or [],
        )
        logger.info("Mail skickat: %s", subject)
    except Exception as e:
        logger.warning("Mail misslyckades ('%s'): %s", subject, e)
