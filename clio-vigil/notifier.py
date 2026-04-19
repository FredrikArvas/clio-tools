"""
clio-vigil — notifier.py
=========================
Daglig digest-mail med nya bevakningsfynd.

Samlar alla indexed-objekt sedan senaste digest,
formaterar rubrik + summary per objekt och skickar
till clio@arvas.se via SMTP (samma server som clio-agent-mail).

Format per objekt:
  Rubrik (källa · datum · mognadsnivå)
  2-3 meningar summary
  Länk till URL

Miljövariabler (.env):
  SMTP_HOST, SMTP_PORT   — SMTP-server (SSL port 465)
  SMTP_USER              — avsändaradress (clio@arvas.se)
  SMTP_PASSWORD          — lösenord
  DIGEST_TO              — mottagaradress (default: fredrik@arvas.se)

Körning:
  python notifier.py --run [--domain ufo] [--dry-run]
  python notifier.py --preview   (visa digest utan att skicka)
"""

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from orchestrator import init_db, transition

logger = logging.getLogger(__name__)

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

SMTP_HOST   = os.getenv("SMTP_HOST", "")
SMTP_PORT   = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER   = os.getenv("SMTP_USER", "clio@arvas.se")
SMTP_PASS   = os.getenv("SMTP_PASSWORD", "")
DIGEST_TO   = os.getenv("DIGEST_TO", "fredrik@arvas.se")

# ---------------------------------------------------------------------------
# Hämta objekt för digest
# ---------------------------------------------------------------------------

def _fetch_digest_items(conn, domain: Optional[str] = None,
                        limit: int = 30) -> list[dict]:
    """
    Hämtar indexed-objekt med summary som ännu ej notifierats.
    Sorterat på priority_score DESC.
    """
    query = """
        SELECT id, domain, title, summary, url, source_name,
               source_maturity, published_at, priority_score
        FROM vigil_items
        WHERE state = 'indexed'
          AND summary IS NOT NULL AND summary != ''
          {}
        ORDER BY priority_score DESC
        LIMIT ?
    """.format("AND domain = ?" if domain else "")

    params = (domain, limit) if domain else (limit,)
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Formatering
# ---------------------------------------------------------------------------

_MATURITY_LABEL = {
    "tidig":     "🟡 tidig källa",
    "etablerad": "🟢 etablerad",
    "akademisk": "🔵 akademisk",
}


def _fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        return iso[:10]
    except Exception:
        return "—"


def _format_item_text(item: dict, idx: int) -> str:
    """Formaterar ett objekt som plain text-block."""
    maturity = _MATURITY_LABEL.get(item["source_maturity"], item["source_maturity"])
    header   = (
        f"{idx}. {item['title'] or '(utan rubrik)'}\n"
        f"   {item['source_name'] or '—'} · {_fmt_date(item['published_at'])} · {maturity}"
    )
    summary = item["summary"] or "(ingen sammanfattning)"
    url     = item["url"] or ""
    return f"{header}\n\n   {summary}\n\n   🔗 {url}"


def _format_item_html(item: dict, idx: int) -> str:
    """Formaterar ett objekt som HTML-block."""
    import html
    maturity = _MATURITY_LABEL.get(item["source_maturity"], item["source_maturity"])
    title    = html.escape(item["title"] or "(utan rubrik)")
    source   = html.escape(item["source_name"] or "—")
    date     = _fmt_date(item["published_at"])
    summary  = html.escape(item["summary"] or "(ingen sammanfattning)")
    url      = html.escape(item["url"] or "")

    return f"""
<div style="margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid #e0d8c8;">
  <p style="margin:0 0 4px 0;font-size:15px;font-weight:bold;color:#2A3F6F;">{idx}. {title}</p>
  <p style="margin:0 0 8px 0;font-size:12px;color:#888;">{source} &middot; {date} &middot; {maturity}</p>
  <p style="margin:0 0 8px 0;font-size:14px;color:#3D2E0A;line-height:1.5;">{summary}</p>
  <a href="{url}" style="font-size:13px;color:#4A6FA5;">Öppna källa →</a>
</div>"""


def build_digest(items: list[dict], domain: Optional[str] = None) -> tuple[str, str, str]:
    """
    Bygger digest-mail: (subject, plain_body, html_body).
    """
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dom_label = domain.upper() if domain else "ALLA DOMÄNER"
    subject  = f"[Clio-Vigil] {dom_label} — {today} ({len(items)} fynd)"

    if not items:
        plain = f"Inga nya fynd idag ({today})."
        html  = f"<p>Inga nya fynd idag ({today}).</p>"
        return subject, plain, html

    # Plain text
    plain_parts = [
        f"Clio-Vigil — Daglig digest {today}",
        f"Domän: {dom_label}  |  {len(items)} objekt",
        "─" * 50,
    ]
    for i, item in enumerate(items, 1):
        plain_parts.append(_format_item_text(item, i))
        plain_parts.append("")

    plain_parts.append("─" * 50)
    plain_parts.append("Genererat av clio-vigil · Arvas International AB")
    plain = "\n".join(plain_parts)

    # HTML
    html_items = "\n".join(_format_item_html(item, i) for i, item in enumerate(items, 1))
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#F7F2E8;padding:20px;">
<div style="max-width:640px;margin:auto;background:#fff;padding:24px;
            border-radius:6px;border:1px solid #EDE5D0;">
  <h2 style="color:#2A3F6F;margin-top:0;">🔭 Clio-Vigil — Daglig digest</h2>
  <p style="color:#888;margin-top:-8px;">{today} &middot; {dom_label} &middot; {len(items)} fynd</p>
  <hr style="border:none;border-top:1px solid #EDE5D0;margin:16px 0;">
  {html_items}
  <p style="font-size:12px;color:#aaa;margin-top:24px;">
    Genererat av clio-vigil &middot; Arvas International AB
  </p>
</div>
</body>
</html>"""

    return subject, plain, html


# ---------------------------------------------------------------------------
# Sändning
# ---------------------------------------------------------------------------

def send_digest(subject: str, plain: str, html: str,
                dry_run: bool = False) -> bool:
    """Skickar digest-mail via clio-agent-mail smtp_client. Returnerar True vid lyckat sändning."""
    if dry_run:
        logger.info(f"[DRY-RUN] Skulle skicka: {subject}")
        print(f"\n{'='*60}\n{plain}\n{'='*60}")
        return True

    # Använd clio-agent-mails smtp_client som har fungerande konfiguration
    import sys
    import configparser
    from pathlib import Path

    agent_mail_dir = Path(__file__).parent.parent / "clio-agent-mail"
    if str(agent_mail_dir) not in sys.path:
        sys.path.insert(0, str(agent_mail_dir))

    try:
        import smtp_client

        config = configparser.ConfigParser()
        config.read(agent_mail_dir / "clio.config")

        # Läs lösenord från clio-agent-mail .env
        from dotenv import load_dotenv
        load_dotenv(agent_mail_dir / ".env", override=False)
        imap_pass = os.getenv("IMAP_PASSWORD_CLIO", "")
        if not imap_pass:
            raise EnvironmentError("IMAP_PASSWORD_CLIO saknas i clio-agent-mail/.env")

        # Injicera lösenord i config (smtp_client läser från config)
        config.set("mail", "imap_password_clio", imap_pass)

        smtp_client.send_email(
            config=config,
            from_account_key="clio",
            to_addr=DIGEST_TO,
            subject=subject,
            body=plain,
            html_body=html,
        )
        logger.info(f"Digest skickad via clio-agent-mail: clio → {DIGEST_TO} | {subject}")
        return True

    except Exception as e:
        logger.error(f"SMTP-fel via clio-agent-mail: {e}")
        return False


# ---------------------------------------------------------------------------
# Markera som notifierade
# ---------------------------------------------------------------------------

def _mark_notified(conn, item_ids: list[int]) -> None:
    for item_id in item_ids:
        transition(conn, item_id, "notified",
                   notified_at=datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Kör digest
# ---------------------------------------------------------------------------

def run_digest(conn, domain: Optional[str] = None,
               dry_run: bool = False, limit: int = 30) -> dict:
    """
    Hämtar fynd, bygger digest, skickar mail och markerar som notifierade.
    Returnerar räknare.
    """
    items = _fetch_digest_items(conn, domain=domain, limit=limit)

    if not items:
        logger.info("Inga nya fynd att rapportera")
        return {"sent": 0, "items": 0}

    subject, plain, html = build_digest(items, domain)
    ok = send_digest(subject, plain, html, dry_run=dry_run)

    if ok and not dry_run:
        _mark_notified(conn, [item["id"] for item in items])

    return {"sent": 1 if ok else 0, "items": len(items)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="clio-vigil notifier — daglig digest-mail"
    )
    parser.add_argument("--run", action="store_true",
                        help="Skicka digest")
    parser.add_argument("--preview", action="store_true",
                        help="Förhandsgranska utan att skicka")
    parser.add_argument("--domain", type=str,
                        help="Begränsa till domän")
    parser.add_argument("--dry-run", action="store_true",
                        help="Logga men skicka inte")
    parser.add_argument("--limit", type=int, default=30,
                        help="Max objekt i digest (default: 30)")
    args = parser.parse_args()

    conn = init_db()

    if args.preview:
        items = _fetch_digest_items(conn, domain=args.domain, limit=args.limit)
        _, plain, _ = build_digest(items, args.domain)
        print(plain)

    elif args.run or args.dry_run:
        counts = run_digest(
            conn,
            domain=args.domain,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(
            f"\n✓ Digest: {counts['items']} objekt"
            + (" (dry-run)" if args.dry_run else " skickade")
        )

    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    _main()
