"""
clio-vigil — pitcher.py
========================
Tar en händelsebeskrivning, matchar mot journalistprofiler och genererar
individuella pitch-utkast via Claude.

Flöde:
  event_text → matchning mot journalist-profiler (Claude) → pitch-utkast per journalist
             → valfri leverans via clio-agent-mail

Körlägen:
  python main.py --pitch "UAP-rapport från Pentagon publiceras"
  python main.py --pitch "..." --domain ufo --send --from-account uap

Designbeslut:
  - Matching görs av Claude (enklare än Qdrant-embeddings i MVP)
  - Pitch-utkast skrivs på svenska med tomma fält för avsändaren att fylla i
  - dry_run=True skriver till stdout, aldrig till mail
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

MAX_JOURNALISTS_PER_PITCH = 10


# ---------------------------------------------------------------------------
# Matchning
# ---------------------------------------------------------------------------

def _match_journalists(conn, event_text: str, domain: Optional[str]) -> list[dict]:
    """
    Returnerar de journalister som sannolikt är intresserade av event_text.
    Använder Claude för att poängsätta relevans mot profil + titlar.
    """
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic-paketet saknas")
        return []

    domain_clause = "WHERE j.profile IS NOT NULL" + (" AND j.domain = ?" if domain else "")
    params = [domain] if domain else []

    journalists = conn.execute(
        f"""SELECT j.id, j.name, j.publication, j.profile, j.topics, j.email
            FROM journalists j
            {domain_clause}
            ORDER BY j.article_count DESC
            LIMIT 50""",
        params,
    ).fetchall()

    if not journalists:
        logger.warning("Inga journalister med profil hittades.")
        return []

    # Bygg lista för Claude att bedöma
    journalist_list = "\n".join(
        f"{i+1}. {j['name']} ({j['publication']}): {j['profile'][:200]}"
        for i, j in enumerate(journalists)
    )

    prompt = (
        f"Du är en PR-strateg. Nedan är en händelse och en lista journalister med profiler.\n"
        f"Välj de {MAX_JOURNALISTS_PER_PITCH} journalister som mest sannolikt är intresserade "
        f"av händelsen. Svara ENBART med ett JSON-objekt på formen:\n"
        f'{{\"matches\": [{{\"index\": 1, \"reason\": \"...\"}}, ...]}}\n\n'
        f"Händelse:\n{event_text}\n\n"
        f"Journalister:\n{journalist_list}"
    )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Extrahera JSON
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            logger.error("Claude returnerade inte JSON: %s", raw[:200])
            return []
        data = json.loads(m.group())
        matches = data.get("matches", [])
    except Exception as exc:
        logger.error("Matchning misslyckades: %s", exc)
        return []

    result = []
    for match in matches:
        idx = match.get("index", 0) - 1
        if 0 <= idx < len(journalists):
            j = dict(journalists[idx])
            j["match_reason"] = match.get("reason", "")
            result.append(j)

    return result


# ---------------------------------------------------------------------------
# Pitch-generering
# ---------------------------------------------------------------------------

def _generate_pitch(journalist: dict, event_text: str) -> str:
    """Genererar ett personaliserat pitch-utkast för en enskild journalist."""
    try:
        import anthropic
    except ImportError:
        return "(anthropic-paketet saknas)"

    profile = journalist.get("profile", "")
    match_reason = journalist.get("match_reason", "")

    prompt = (
        f"Du är en PR-rådgivare. Skriv ett pitch-mail till journalisten "
        f"{journalist['name']} på {journalist['publication']}.\n\n"
        f"Journalistens profil: {profile}\n"
        f"Varför relevant: {match_reason}\n\n"
        f"Händelse att pitcha:\n{event_text}\n\n"
        f"Skriv mailet på svenska. Format:\n"
        f"- Ämnesrad (på svenska)\n"
        f"- Hälsning och en personlig koppling till journalistens bevakning\n"
        f"- 2-3 meningar om händelsen och varför det är en nyhet\n"
        f"- Erbjudande om underlag (lämna [KÄLLA/EXPERT] som platshållare)\n"
        f"- Avslutning\n\n"
        f"Håll det kort: max 120 ord i brödtexten. Avsändarnamn = [AVSÄNDARE]."
    )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        return f"(Fel vid generering: {exc})"


# ---------------------------------------------------------------------------
# Huvud-entry
# ---------------------------------------------------------------------------

def run_pitch(
    conn,
    event_text: str,
    domain: Optional[str] = None,
    send: bool = False,
    from_account: str = "clio",
    dry_run: bool = False,
    odoo_event_id: Optional[int] = None,
    odoo_env=None,
) -> list[dict]:
    """
    Kör full pitch-pipeline för ett event. Returnerar lista med pitch-objekt.
    Varje objekt: {journalist, pitch_text, sent}
    """
    logger.info("Pitch-pipeline start: %s…", event_text[:60])

    matched = _match_journalists(conn, event_text, domain)
    if not matched:
        logger.warning("Inga matchande journalister hittades.")
        return []

    logger.info("%d journalister matchade — genererar pitch-utkast…", len(matched))

    results = []
    for journalist in matched:
        pitch_text = _generate_pitch(journalist, event_text)
        sent = False

        if send and not dry_run and journalist.get("email"):
            sent = _send_pitch(journalist, pitch_text, from_account)

        results.append({
            "journalist": journalist["name"],
            "publication": journalist["publication"],
            "email": journalist.get("email", ""),
            "match_reason": journalist.get("match_reason", ""),
            "pitch_text": pitch_text,
            "sent": sent,
        })

    # Spara körningen till SQLite
    _log_pitch_run(conn, event_text, domain, results)

    # Skriv pitch-poster tillbaka till Odoo om event_id finns
    if odoo_event_id and odoo_env and not dry_run:
        _write_pitches_to_odoo(odoo_env, odoo_event_id, results)

    return results


def _write_pitches_to_odoo(odoo_env, event_odoo_id: int, results: list[dict]) -> None:
    """Skapar clio.lobbying.pitch-poster i Odoo för varje genererat utkast."""
    try:
        Pitch = odoo_env["clio.lobbying.pitch"]
        Journalist = odoo_env["clio.lobbying.journalist"]

        # Sätt event till review-läge
        try:
            odoo_env["clio.lobbying.event"].browse(event_odoo_id).write({"state": "review"})
        except Exception as exc:
            logger.warning("Kunde inte uppdatera event-tillstånd: %s", exc)

        for r in results:
            # Hitta journalist i Odoo via namn
            journalist = Journalist.search(
                [("name", "=", r["journalist"])], limit=1
            )
            if not journalist:
                logger.warning("Journalist ej hittad i Odoo: %s", r["journalist"])
                continue

            # Undvik dubbletter
            existing = Pitch.search([
                ("event_id", "=", event_odoo_id),
                ("journalist_id", "=", journalist.id),
            ], limit=1)
            if existing:
                continue

            # Extrahera ämnesrad ur pitch_text
            subject = ""
            for line in (r.get("pitch_text") or "").splitlines():
                if line.lower().startswith("ämnesrad"):
                    subject = line.split(":", 1)[-1].strip()
                    break

            Pitch.create({
                "event_id":      event_odoo_id,
                "journalist_id": journalist.id,
                "pitch_text":    r.get("pitch_text", ""),
                "subject":       subject,
                "match_reason":  r.get("match_reason", ""),
                "state":         "draft",
            })
            logger.info("Pitch skapad i Odoo: %s → event %d", r["journalist"], event_odoo_id)

    except Exception as exc:
        logger.error("Odoo write-back misslyckades: %s", exc)


def _send_pitch(journalist: dict, pitch_text: str, from_account: str) -> bool:
    """Skickar pitch via clio-agent-mail (direktimport, ingen self-SSH).
    OBS: kräver .env i ~/19.0/clio-tools/clio-agent-mail/ — saknas i nuläget."""
    import importlib.util, os, configparser, sys as _sys
    from pathlib import Path
    from dotenv import load_dotenv

    email = journalist.get("email", "")
    if not email:
        logger.warning("Inget mail för %s — hoppar.", journalist["name"])
        return False

    subject = ""
    for line in pitch_text.splitlines():
        if line.lower().startswith("ämnesrad"):
            subject = line.split(":", 1)[-1].strip()
            break
    if not subject:
        subject = f"Nyhet: {journalist.get('match_reason', 'se bifogat')[:60]}"

    mail_dir = Path.home() / "19.0/clio-tools/clio-agent-mail"

    try:
        load_dotenv(mail_dir.parent / ".env")
        load_dotenv(mail_dir / ".env", override=True)

        spec = importlib.util.spec_from_file_location(
            "smtp_client", mail_dir / "smtp_client.py"
        )
        smtp_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smtp_mod)

        config = configparser.ConfigParser(interpolation=None)
        config.read(str(mail_dir / "clio.config"), encoding="utf-8")
        for k in config.get("mail", "accounts").split(","):
            k = k.strip()
            v = os.environ.get(f"IMAP_PASSWORD_{k.upper()}")
            if v:
                config.set("mail", f"imap_password_{k}", v)

        smtp_mod.send_email(
            config=config,
            from_account_key=from_account,
            to_addr=email,
            subject=subject,
            body=pitch_text,
        )
        logger.info("Pitch skickat till %s <%s>", journalist["name"], email)
        return True
    except Exception as exc:
        logger.error("Pitch-sändning misslyckades: %s", exc)
        return False


def _log_pitch_run(conn, event_text: str, domain: Optional[str], results: list[dict]) -> None:
    """Sparar en pitch-körning i pitch_runs-tabellen."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """INSERT INTO pitch_runs (event_text, domain, journalist_count, created_at)
               VALUES (?, ?, ?, ?)""",
            (event_text[:500], domain, len(results), now),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Kunde inte logga pitch-körning: %s", exc)
