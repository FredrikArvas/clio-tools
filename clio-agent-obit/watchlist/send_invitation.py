"""
watchlist/send_invitation.py — Skickar inbjudningsmail med personanpassad bevakningslista-mall

Bilagan är förformaterad med mottagarens e-post som filnamn och deras eget
namn som exempelrad, redo att öppnas i Excel och fyllas i.

Mottagaren svarar med [clio-obit] i ämnesraden — auto-import via clio-agent-mail (Sprint 3).

Körning:
    python send_invitation.py --to-name "Ulrika Arvas" --to-email ulrika@arvas.se
    python send_invitation.py --to-name "Ulrika Arvas" --to-email ulrika@arvas.se --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from notifier import _load_config, _create_smtp


def _make_csv(to_name: str, to_email: str) -> str:
    """Skapar en personanpassad CSV-mall som sträng."""
    parts = to_name.strip().split(None, 1)
    fornamn  = parts[0] if parts else to_name
    efternamn = parts[1] if len(parts) > 1 else ""

    lines = [
        "efternamn,fornamn,fodelsear,hemort,prioritet,kalla",
        f"# Bevakningslista för {to_email}",
        "# Fyll i och svara på det här mailet med [clio-obit] i ämnesraden.",
        "#",
        "# Fält:",
        "#   efternamn, fornamn  — obligatoriska",
        "#   fodelsear           — födelseår, t.ex. 1948 (lämna tomt om okänt)",
        "#   hemort              — ort, t.ex. Haninge (lämna tomt om okänt)",
        "#   prioritet           — viktig / normal / bra_att_veta",
        "#   kalla               — manuell (för manuella tillägg)",
        "#",
        "# Prioritetsnivåer:",
        "#   viktig       → du får ett mail direkt om personen dyker upp",
        "#   normal       → samlas i en daglig sammanfattning",
        "#   bra_att_veta → daglig sammanfattning, lägre prioritet",
        "#",
        "# Spara filen och svara på mailet. Ämnesraden måste innehålla [clio-obit].",
        "#",
    ]

    # Exempelrad med mottagarens eget namn
    if efternamn:
        lines.append(f"{efternamn},{fornamn},,, viktig,manuell")
    else:
        lines.append(f"Efternamn,{fornamn},,,viktig,manuell")

    return "\n".join(lines) + "\n"


_BODY = """\
Hej {fornamn},

Du är nu inbjuden till dödsannonsbevakningen — ett system som automatiskt
söker igenom svenska dödsannonser och meddelar dig om någon på din lista dyker upp.

Så här gör du:

  1. Öppna den bifogade filen {filename} i Excel eller ett textprogram.
  2. Fyll i de personer du vill bevaka — ett namn per rad.
     Ta inte bort kommentarsraderna (börjar med #), de behövs inte heller.
  3. Spara filen med samma namn: {filename}
  4. Svara på det här mailet med filen bifogad.
     Viktigt: behåll "[clio-obit]" i ämnesraden så importeras den automatiskt.

Din fil {filename} innehåller din egen rad som exempel — ändra eller ta bort den.

Prioritetsnivåer i korthet:
  viktig        → mail direkt när träff hittas
  normal        → daglig sammanfattning
  bra_att_veta  → daglig sammanfattning, lägsta prioritet

Hör av dig om du har frågor.

— clio-agent-obit
"""


def send_invitation(to_name: str, to_email: str, dry_run: bool = False) -> None:
    cfg      = _load_config()
    smtp_user  = cfg.get("smtp", {}).get("user", "")
    from_label = cfg.get("notify", {}).get("from_label", "clio-agent-obit")

    fornamn  = to_name.strip().split()[0]
    filename = f"{to_email}.csv"
    csv_content = _make_csv(to_name, to_email)

    subject = "[clio-obit] Dödsannonsbevakning — din bevakningslista"
    body    = _BODY.format(fornamn=fornamn, filename=filename)

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"]    = f"{from_label} <{smtp_user}>"
    msg["To"]      = to_email
    msg["Reply-To"] = smtp_user

    msg.attach(MIMEText(body, "plain", "utf-8"))

    # CSV-bilaga
    part = MIMEBase("text", "csv", charset="utf-8")
    part.set_payload(csv_content.encode("utf-8"))
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)

    if dry_run:
        print(f"[dry-run] Till:    {to_name} <{to_email}>")
        print(f"[dry-run] Ämne:    {subject}")
        print(f"[dry-run] Bilaga:  {filename}")
        print(f"\n--- CSV-förhandsgranskning ---")
        print(csv_content)
        return

    with _create_smtp(cfg) as smtp:
        smtp.sendmail(smtp_user, to_email, msg.as_string())
    print(f"Inbjudan skickad till {to_name} <{to_email}>")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Skicka inbjudningsmail med bevakningslista-mall")
    p.add_argument("--to-name",  required=True, help="Mottagarens fullständiga namn")
    p.add_argument("--to-email", required=True, help="Mottagarens e-postadress")
    p.add_argument("--dry-run",  action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    send_invitation(args.to_name, args.to_email, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
