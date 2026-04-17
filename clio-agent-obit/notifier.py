"""
notifier.py — Epost-notifiering för clio-agent-obit

Skickar:
  - Direktnotis (viktig) — ett mail per träff, omedelbart
  - Daglig digest (normal + bra_att_veta) — ett sammanfattande mail

Konfiguration läses från TVÅ filer:
  config.yaml  → host, port, user, mottagare (icke-hemligt, versioneras)
  .env         → SMTP_PASSWORD (eller annat namn enligt password_env)

Stödjer både SMTP_SSL (port 465, use_ssl: true) och plain SMTP + STARTTLS
(port 587, use_starttls: true).
"""

from __future__ import annotations

import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import yaml
from pathlib import Path
from dotenv import load_dotenv
_BASE_DIR = Path(os.path.abspath(__file__)).parent
load_dotenv(_BASE_DIR.parent / ".env")          # root clio-tools/.env (prioritet)
load_dotenv(_BASE_DIR / ".env")                  # lokal fallback (standalone)

from matcher import Match


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def _load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"config.yaml saknas: {CONFIG_PATH}")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _create_smtp(cfg: dict) -> smtplib.SMTP:
    """Skapar och autentiserar en SMTP-anslutning enligt config.yaml + .env."""
    smtp_cfg = cfg.get("smtp", {})
    host = smtp_cfg.get("host")
    port = int(smtp_cfg.get("port", 587))
    user = smtp_cfg.get("user")
    use_ssl = bool(smtp_cfg.get("use_ssl", False))
    use_starttls = bool(smtp_cfg.get("use_starttls", True))
    pw_var = smtp_cfg.get("password_env", "SMTP_PASSWORD")
    password = os.getenv(pw_var, "").strip()

    if not host or not user:
        raise ValueError("config.yaml: smtp.host och smtp.user måste vara satta")
    if not password:
        raise ValueError(f"{pw_var} saknas i .env (eller är tomt)")

    if use_ssl:
        smtp = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(host, port)
        if use_starttls:
            smtp.starttls(context=ssl.create_default_context())

    smtp.login(user, password)
    return smtp


def _send(subject: str, body_text: str, body_html: Optional[str] = None,
          to_addr: Optional[str] = None) -> None:
    cfg = _load_config()
    notify = cfg.get("notify", {})
    # to_addr-argumentet vinner över config.yaml (används av per-bevakare-notiser)
    if not to_addr:
        to_addr = notify.get("to", "")
    from_label = notify.get("from_label", "clio-agent-obit")
    from_user = cfg.get("smtp", {}).get("user", "")

    if not to_addr:
        raise ValueError("Ingen mottagaradress — sätt notify.to i config.yaml eller skicka to_addr")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_label} <{from_user}>"
    msg["To"] = to_addr

    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    with _create_smtp(cfg) as smtp:
        smtp.sendmail(from_user, to_addr, msg.as_string())


def send_urgent(match: Match, to_addr: Optional[str] = None) -> None:
    """Skickar direktnotis för en viktig träff."""
    e = match.entry
    a = match.announcement
    namn = f"{e.fornamn} {e.efternamn}".strip()

    subject = f"[clio-agent-obit] ⚠️ {namn} — dödsannons hittad"

    text = (
        f"clio-agent-obit har hittat en möjlig träff på din bevakningslista.\n\n"
        f"Person i listan:  {namn}\n"
        f"Prioritet:        {e.prioritet}\n"
        f"Födelseår (lista):{e.fodelsear or 'okänt'}\n"
        f"Hemort (lista):   {e.hemort or 'okänd'}\n\n"
        f"Annons:\n"
        f"  Namn:           {a.namn}\n"
        f"  Födelseår:      {a.fodelsear or 'ej angivet i annonsen'}\n"
        f"  Publicerad:     {a.publiceringsdatum}\n"
        f"  Länk:           {a.url}\n\n"
        f"Konfidenspoäng: {match.score}/100\n"
        f"Poängfördelning: {match.score_breakdown}\n\n"
        f"— clio-agent-obit"
    )

    _send(subject, text, to_addr=to_addr)


def send_digest(matches: list[Match], run_date: Optional[str] = None,
                to_addr: Optional[str] = None) -> None:
    """Skickar daglig digest med normal + bra_att_veta-träffar."""
    if not matches:
        return

    date_str = run_date or datetime.now().strftime("%Y-%m-%d")
    subject = f"[clio-agent-obit] Daglig sammanfattning {date_str} — {len(matches)} träff(ar)"

    lines = [
        f"clio-agent-obit daglig sammanfattning — {date_str}",
        f"{len(matches)} träff(ar) på bevakningslistan\n",
        "=" * 50,
    ]

    for m in sorted(matches, key=lambda x: x.score, reverse=True):
        e = m.entry
        a = m.announcement
        namn = f"{e.fornamn} {e.efternamn}".strip()
        lines += [
            f"\n{namn}  [{e.prioritet}]  poäng: {m.score}",
            f"  Annons: {a.namn}",
            f"  Publicerad: {a.publiceringsdatum}",
            f"  Länk: {a.url}",
        ]

    lines += ["", "=" * 50, "— clio-agent-obit"]
    text = "\n".join(lines)

    _send(subject, text, to_addr=to_addr)
