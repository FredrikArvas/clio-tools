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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from orchestrator import init_db, transition

logger = logging.getLogger(__name__)

_here = Path(__file__).parent
load_dotenv(_here.parent / ".env")
load_dotenv(_here / ".env", override=True)

DIGEST_TO = os.getenv("DIGEST_TO", "fredrik@arvas.se")

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
                to_addr: Optional[str] = None,
                dry_run: bool = False) -> bool:
    """Skickar digest-mail via clio_core.mail. Returnerar True vid lyckat sändning."""
    to = to_addr or DIGEST_TO
    if dry_run:
        logger.info(f"[DRY-RUN] Skulle skicka till {to}: {subject}")
        print(f"\n{'='*60}\n[Till: {to}]\n{plain}\n{'='*60}")
        return True

    from clio_core import mail
    return mail.send(to, subject, plain, html)


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
               dry_run: bool = False, limit: int = 30,
               odoo_env=None) -> dict:
    """
    Hämtar fynd, bygger digest, skickar mail och markerar som notifierade.

    Om odoo_env är satt och det finns aktiva prenumeranter → per-prenumerant-läge.
    Annars → fallback till DIGEST_TO från .env.

    Returnerar räknare: sent, items, (subscribers om Odoo-läge).
    """
    if odoo_env is not None:
        return _run_digest_odoo(conn, odoo_env, domain=domain,
                                dry_run=dry_run, limit=limit)
    return _run_digest_fallback(conn, domain=domain, dry_run=dry_run, limit=limit)


def _run_digest_fallback(conn, domain: Optional[str] = None,
                         dry_run: bool = False, limit: int = 30) -> dict:
    """Enkel digest till DIGEST_TO (ursprungligt beteende)."""
    items = _fetch_digest_items(conn, domain=domain, limit=limit)
    if not items:
        logger.info("Inga nya fynd att rapportera")
        return {"sent": 0, "items": 0}

    subject, plain, html = build_digest(items, domain)
    ok = send_digest(subject, plain, html, dry_run=dry_run)

    if ok and not dry_run:
        _mark_notified(conn, [item["id"] for item in items])

    return {"sent": 1 if ok else 0, "items": len(items)}


def _run_digest_odoo(conn, odoo_env, domain: Optional[str] = None,
                     dry_run: bool = False, limit: int = 30) -> dict:
    """
    Per-prenumerant-digest driven av Odoo.

    Flöde:
      1. Läs aktiva prenumeranter från Odoo.
      2. Hämta alla indexed-objekt (ännu ej notifierade).
      3. Per prenumerant: filtrera på domäner de följer.
      4. Bygg och skicka individuell digest.
      5. Skapa delivery-poster i Odoo.
      6. Markera levererade objekt som notified i SQLite.

    Faller tillbaka på _run_digest_fallback om inga prenumeranter finns.
    """
    from odoo_reader import load_subscribers
    from odoo_writer import write_deliveries

    subscribers = load_subscribers(odoo_env)
    if not subscribers:
        logger.info("Inga aktiva prenumeranter i Odoo — fallback till DIGEST_TO")
        return _run_digest_fallback(conn, domain=domain, dry_run=dry_run, limit=limit)

    all_items = _fetch_digest_items(conn, domain=domain, limit=limit)
    if not all_items:
        logger.info("Inga nya fynd att rapportera")
        return {"sent": 0, "items": 0, "subscribers": len(subscribers)}

    today      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_str    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    total_sent = 0
    all_deliveries: list[dict] = []
    notified_ids: set[int] = set()

    for sub in subscribers:
        email = sub["email"]
        if not email:
            logger.warning(
                "Prenumerant %d (Odoo) saknar e-post — hoppar över", sub["id"]
            )
            continue

        # Filtrera på vilka domäner prenumeranten följer
        sub_items = [
            item for item in all_items
            if (item["domain"] == "ufo" and sub["follows_ufo"])
            or (item["domain"] == "ai"  and sub["follows_ai"])
        ]
        if not sub_items:
            continue

        subject, plain, html = build_digest(sub_items, domain)
        ok = send_digest(subject, plain, html, to_addr=email, dry_run=dry_run)

        if ok:
            total_sent += 1
            for item in sub_items:
                notified_ids.add(item["id"])
                all_deliveries.append({
                    "subscriber_odoo_id": sub["id"],
                    "item_url":           item["url"],
                    "delivered_at":       now_str,
                    "digest_date":        today,
                })

    # Skriv delivery-poster och uppdatera SQLite
    if not dry_run:
        if all_deliveries:
            write_deliveries(odoo_env, all_deliveries)
        if notified_ids:
            _mark_notified(conn, list(notified_ids))

    return {
        "sent":        total_sent,
        "items":       len(notified_ids),
        "subscribers": len(subscribers),
    }


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
