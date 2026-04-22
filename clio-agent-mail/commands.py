"""
commands.py — mail-kommandosystem för clio-agent-mail

Admin skickar ett mail till clio@ eller info@:
  Ämnesrad  = kommando  (case-insensitive, synonymer per språk)
  Brödtext  = argument  (mottagaradress, #kodord, fritext)

Kommandon
─────────
  list        → projekt + kodord från Projektmasterlistan
  waiting     → väntande mail i DB
  status      → systemöversikt (poll-tid, statuskonton)
  whitelist   → visa vitlistan / lägg till adress (adress i brödtext)
  blacklist   → svartlista adress (adress i brödtext)
  help        → kortfattad hjälp för alla användare
  adminhelp   → adminkommandon (visas bara för admins)
  manual      → fullständig dokumentation på adminens språk
  onboarding  → skicka välkomstmail till ny kontakt
  prompt      → skicka instruktionsmail till annan med #kodord som kontext
  language    → byt din språkpreferens (språkkod i brödtext, t.ex. "en")
"""
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime

import state
import notion_data as notion_client

logger = logging.getLogger("clio-mail.commands")

# ── Synonymtabell ─────────────────────────────────────────────────────────────
# Kanoniskt namn → lista av alias (lowercase, alla språk)

COMMAND_MAP: dict[str, list[str]] = {
    "list":       ["list", "lista", "liste", "lister", "projekt", "projects"],
    "waiting":    ["waiting", "väntande", "väntar", "en attente", "warten"],
    "status":     ["status"],
    "whitelist":  ["whitelist", "vitlista"],
    "blacklist":  ["blacklist", "svartlista"],
    "help":       ["help", "hjälp", "aide", "hilfe", "ayuda"],
    "adminhelp":  ["adminhelp", "systemhelp", "adminhjälp", "admin"],
    "manual":     ["manual", "manuell", "handbuch", "manuel"],
    "onboarding": ["onboarding", "welcome", "välkommen", "bienvenue", "willkommen"],
    "prompt":     ["prompt", "instruera", "instruct", "instruktion", "send", "skicka"],
    "language":   ["language", "språk", "langue", "sprache", "lang"],
    # Dolt kommando: visas bara i /manual för användare med :rw-behörighet
    "update":     ["update", "uppdatera", "opdater", "aktualisieren"],
    "ncc_ny":          ["nytt ncc", "new ncc", "ncc ny", "ncc new", "skapa ncc"],
    "ncc_lista":       ["ncc lista", "ncc list", "projektlista", "project list"],
    "interview_start": ["intervju start", "interview start", "starta intervju", "start interview"],
    "interview_stop":  ["intervju stopp", "interview stop", "avsluta intervju", "stop interview"],
}

# Kommandon som kräver admin-behörighet
ADMIN_COMMANDS = {
    "list", "waiting", "status", "whitelist", "blacklist",
    "adminhelp", "manual", "onboarding", "prompt", "language",
    "ncc_ny", "ncc_lista", "interview_start", "interview_stop",
}

# Nationella TLD → ISO 639-1 språkkod
_TLD_LANG: dict[str, str] = {
    "se": "sv", "no": "no", "dk": "da", "fi": "fi",
    "fr": "fr", "de": "de", "at": "de", "ch": "de",
    "nl": "nl", "be": "nl", "es": "es", "pt": "pt",
    "it": "it", "pl": "pl", "cz": "cs", "sk": "sk",
    "hu": "hu", "ro": "ro", "bg": "bg", "hr": "hr",
    "lt": "lt", "lv": "lv", "ee": "et",
    "gb": "en", "ie": "en", "au": "en", "nz": "en",
    "us": "en", "ca": "en",
    "br": "pt", "mx": "es", "ar": "es", "cl": "es",
    "cn": "zh", "jp": "ja", "kr": "ko",
}


# ── Datatyper ─────────────────────────────────────────────────────────────────

@dataclass
class OutboundMail:
    to_addr: str
    subject: str
    body: str
    from_account_key: str = "clio"
    message_id: str = ""


@dataclass
class CommandResult:
    reply_body: str                        # svar tillbaka till admin
    outbound: list[OutboundMail] = field(default_factory=list)
    is_reasoning: bool = False             # True = Clio ber om förtydligande


# ── Kommandoresolvering ───────────────────────────────────────────────────────

def resolve_command(subject: str) -> str | None:
    """
    Mappar ett ämne till ett kanoniskt kommandonamn.
    Matchar på hela ämnet eller första ordet (före mellanslag/tab).
    Returnerar None om inget kommando matchar.
    """
    normalized = subject.strip().lower().lstrip("/")
    # Försök hela ämnet först
    for canonical, aliases in COMMAND_MAP.items():
        if normalized in aliases:
            return canonical
    # Försök första ordet (t.ex. "list ncc #aiguide" → "list")
    first_word = normalized.split()[0] if normalized else ""
    if first_word and first_word != normalized:
        for canonical, aliases in COMMAND_MAP.items():
            if first_word in aliases:
                return canonical
    return None


def is_admin_command(command: str) -> bool:
    return command in ADMIN_COMMANDS


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _detect_language(email: str, config) -> str:
    """
    Detekterar språk från TLD i e-postdomän.
    Nationella TLD:er ger språk direkt.
    Icke-nationella (.com, .net, .org, .io, .ai …) → systemets default_language.
    """
    domain = email.split("@")[-1].lower() if "@" in email else ""
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    if tld in _TLD_LANG:
        return _TLD_LANG[tld]
    return config.get("mail", "default_language", fallback="sv")


def _parse_first_email(body: str) -> tuple[str, str]:
    """
    Extraherar första e-postadress ur brödtexten.
    Returnerar (email, rest_of_body).
    """
    lines = body.strip().splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        match = re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", line)
        if match:
            email = match.group(0).lower()
            rest = "\n".join(lines[i + 1:]).strip()
            return email, rest
    return "", body.strip()


def _parse_kodord(text: str) -> list[str]:
    """Extraherar #kodord ur fritext. Returnerar lista i hittad ordning."""
    return [m.lower() for m in re.findall(r"#(\w+)", text)]


def _resolve_nccs(
    kodord_list: list[str],
    config,
    allowed_kodord: list[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """
    Slår upp kodord mot Projektmasterlistan.
    Returnerar (matchade projekt-dicts, ej hittade kodord).

    allowed_kodord: om satt, filtreras matchningar till bara dessa kodord.
    None = inga begränsningar (admin/write).
    """
    raw = config.get("mail", "knowledge_notion_db_ids", fallback="")
    db_entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not db_entries:
        return [], kodord_list

    db_id = db_entries[0].split(":")[0].strip()
    index = notion_client.get_project_index(db_id)

    matched = []
    not_found = []
    for kw in kodord_list:
        proj = next((p for p in index if p["kodord"] == kw), None)
        if proj:
            if allowed_kodord is None or kw in allowed_kodord:
                matched.append(proj)
            else:
                not_found.append(kw)  # kodord finns men är ej tillåtet för denna användare
        else:
            not_found.append(kw)
    return matched, not_found


def _fetch_ncc_text(proj: dict) -> str:
    """Hämtar Context Card-text för ett projekt."""
    if proj.get("page_id"):
        return notion_client._extract_page_text(proj["page_id"])
    return ""


def _admin_language(sender_email: str, config) -> str:
    """Hämtar adminens språkpreferens (partners-tabell → config default)."""
    return state.get_partner_language(sender_email, config)


# ── Kommandohanterare ─────────────────────────────────────────────────────────

def _cmd_list(mail_item, config) -> CommandResult:
    """
    Returnerar projektlistan från Projektmasterlistan.

    Filtrering:
    - Exkluderar status 'Saknas' för alla användare
    - Tillämpar account-scope (account_scopes.json)
    - Tillämpar user-scope (coded-användare ser bara sina kodord)

    Visning:
    - Grupperas per sfär
    - admin/write: ✓/– NCC-indikator per projekt
    - coded/whitelisted: bara #kodord + projektnamn
    """
    from collections import OrderedDict
    from classifier import extract_sender_email
    from clio_access import AccessManager
    from helpers import _account_key_for

    raw = config.get("mail", "knowledge_notion_db_ids", fallback="")
    db_entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not db_entries:
        return CommandResult("Ingen projektdatabas konfigurerad.")

    db_id = db_entries[0].split(":")[0].strip()
    index = notion_client.get_project_index(db_id)
    if not index:
        return CommandResult("Projektlistan är tom eller otillgänglig.")

    # Bestäm access-nivå
    sender_email = extract_sender_email(mail_item.sender)
    am = AccessManager.from_config(config)
    level = am.get_level({"email": sender_email})
    is_privileged = level in ("admin", "write")

    # Effektivt scope = skärning av user-scope och account-scope
    user_scope = am.get_kodord_scope({"email": sender_email})
    account_key = _account_key_for(mail_item.account, config)
    account_scope = notion_client.load_account_scope(account_key)

    if user_scope is None:
        effective_scope = account_scope
    elif account_scope is None:
        effective_scope = user_scope
    else:
        effective_scope = [k for k in user_scope if k in account_scope]

    # Filtrera: ta bort "Saknas", tillämpa scope, kräv kodord
    STATUS_HIDDEN = {"saknas"}
    STATUS_ORDER  = {"bekräftad": 0, "pågående": 1, "osäker": 2}

    filtered = [
        p for p in index
        if p.get("kodord")
        and p.get("status", "").lower() not in STATUS_HIDDEN
        and (effective_scope is None or p["kodord"] in effective_scope)
    ]

    if not filtered:
        return CommandResult("Inga tillgängliga projekt.")

    # Gruppera per sfär (behåll Notion-ordning)
    groups: OrderedDict[str, list] = OrderedDict()
    for proj in filtered:
        sfar = (proj.get("sfar") or "").strip() or "Övrigt"
        if sfar not in groups:
            groups[sfar] = []
        groups[sfar].append(proj)

    # Sortera inom varje sfär: bekräftad → pågående → osäker → övrigt
    for projs in groups.values():
        projs.sort(key=lambda p: STATUS_ORDER.get(p.get("status", "").lower(), 9))

    # ── Bygg utdata ───────────────────────────────────────────────────────────
    KW = 14   # kolumnbredd för #kodord
    NM = 30   # max tecken för projektnamn

    scope_note = " — dina projekt" if effective_scope is not None else ""
    lines = [f"Projekt ({len(filtered)}){scope_note}", "═" * 46]

    for sfar, projs in groups.items():
        lines.append(f"\n{sfar}")
        for proj in projs:
            kw   = f"#{proj['kodord']}"
            name = proj.get("name", "")
            name = name[:NM] + ("…" if len(name) > NM else "")
            if is_privileged:
                ncc = "✓" if proj.get("page_id") else "–"
                lines.append(f"  {ncc}  {kw:<{KW}} {name}")
            else:
                lines.append(f"  {kw:<{KW}} {name}")

    lines.append("\n" + "═" * 46)
    if is_privileged:
        lines.append("✓ = Context Card finns   – = saknas ännu")
    lines.append("Tip: /prompt #kodord för att inkludera projektkort.")

    return CommandResult("\n".join(lines))


def _cmd_waiting(mail_item, config) -> CommandResult:
    """Returnerar väntande mail."""
    import sqlite3
    with state.get_connection() as conn:
        rows = conn.execute(
            "SELECT sender, subject, date_received FROM mail WHERE status = ? ORDER BY created_at",
            (state.STATUS_WAITING,)
        ).fetchall()

    if not rows:
        return CommandResult("No mail waiting for whitelist decision.")

    sep = "─" * 40
    lines = [f"Waiting ({len(rows)})", sep]
    for i, row in enumerate(rows, 1):
        date = (row["date_received"] or "")[:10]
        subj = (row["subject"] or "")[:45]
        sndr = row["sender"][:35]
        lines.append(f"{i}. {sndr}\n   {subj}  {date}")
    lines.append(sep)
    lines.append("Use clio.py maillog to act on waiting mail.")

    return CommandResult("\n".join(lines))


def _cmd_status(mail_item, config) -> CommandResult:
    """Returnerar systemöversikt."""
    with state.get_connection() as conn:
        counts = {
            row["status"]: row["cnt"]
            for row in conn.execute(
                "SELECT status, COUNT(*) as cnt FROM mail GROUP BY status"
            ).fetchall()
        }
        total = conn.execute("SELECT COUNT(*) as cnt FROM mail").fetchone()["cnt"]

    sep = "─" * 40
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"clio-agent-mail status  {now}",
        sep,
        f"Total mail:  {total}",
        f"WAITING:     {counts.get('WAITING', 0)}",
        f"PENDING:     {counts.get('PENDING', 0)}",
        f"SENT:        {counts.get('SENT', 0)}",
        f"FLAGGED:     {counts.get('FLAGGED', 0)}",
        f"REJECTED:    {counts.get('REJECTED', 0)}",
        sep,
    ]
    return CommandResult("\n".join(lines))


def _cmd_whitelist(mail_item, config) -> CommandResult:
    """Visar vitlistan eller lägger till adress."""
    body = mail_item.body.strip()
    wl_page = config.get("mail", "whitelist_notion_page_id", fallback="")

    if not wl_page:
        return CommandResult("Whitelist page not configured.")

    # Adress i brödtext → lägg till
    email_match = re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", body)
    if email_match:
        addr = email_match.group(0).lower()
        notion_client.add_to_whitelist(wl_page, addr)
        state.upsert_partner(addr, role="contact")
        return CommandResult(f"Added to whitelist: {addr}")

    # Ingen adress → visa listan
    whitelist = notion_client.get_whitelist(wl_page)
    if not whitelist:
        return CommandResult("Whitelist is empty.")

    sep = "─" * 40
    lines = [f"Whitelist ({len(whitelist)} addresses)", sep]
    lines += sorted(whitelist)
    return CommandResult("\n".join(lines))


def _cmd_blacklist(mail_item, config) -> CommandResult:
    """Svartlistar en adress."""
    body = mail_item.body.strip()
    email_match = re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", body)
    if not email_match:
        return CommandResult("Usage: subject=blacklist, body=email@example.com")
    addr = email_match.group(0).lower()
    state.add_to_blacklist(addr)
    return CommandResult(f"Blacklisted: {addr}")


def _cmd_help(mail_item, config) -> CommandResult:
    """Kortfattad hjälp — för alla användare."""
    lang = _admin_language(
        re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", mail_item.sender or "").group(0)
        if re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", mail_item.sender or "") else "",
        config
    )
    # Generera hjälptexten på rätt språk med Claude
    from reply import _get_client, MODEL
    client = _get_client()
    prompt = f"""Generate a brief help message (max 15 lines) for a mail-based AI assistant called Clio.
The user is an external contact, not an admin.
Language: {lang}
Include:
- How to ask questions (just send a mail)
- How to change language: reply with subject=language, body=<code> (e.g. "en", "sv", "fr")
- A link hint: for more help, send subject=/adminhelp (admins only) or reply to any Clio mail
Keep it warm and brief. No bullet symbols except dashes.
Do not reveal system internals."""
    response = client.messages.create(
        model=MODEL, max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return CommandResult(response.content[0].text.strip())


def _cmd_adminhelp(mail_item, config) -> CommandResult:
    """Fullständig adminhjälp."""
    sep = "─" * 40
    lines = [
        "clio-agent-mail — Admin commands",
        sep,
        "Send mail to clio@arvas.international",
        "Subject = command  |  Body = arguments",
        "",
        "COMMANDS",
        "  list          — all projects + #kodord",
        "  waiting       — mail waiting for whitelist decision",
        "  status        — system overview",
        "  whitelist     — show whitelist (body empty)",
        "  whitelist     — add address (body: email@...)",
        "  blacklist     — block address (body: email@...)",
        "  onboarding    — send welcome mail (body: email@...  [Name])",
        "  prompt        — send instruction (body: email@...\n"
        "                  instruction with #kodord for context)",
        "  language      — change your language (body: en / sv / fr / de)",
        "  manual        — full documentation",
        "  help          — brief help (for all users)",
        sep,
        "Synonyms: lista=list, väntande=waiting, vitlista=whitelist, …",
        "All commands are case-insensitive. / prefix optional.",
    ]
    return CommandResult("\n".join(lines))


def _cmd_manual(mail_item, config) -> CommandResult:
    """Fullständig manual på adminens språk."""
    sender_email = re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", mail_item.sender or "")
    sender_email = sender_email.group(0) if sender_email else ""
    lang = _admin_language(sender_email, config)

    from reply import _get_client, MODEL
    client = _get_client()
    prompt = f"""Write a complete manual for a mail-based AI assistant called Clio.
Language: {lang}
Cover:
1. What Clio is (AI assistant handling inboxes clio@arvas.international and info@arvas.international)
2. How external contacts interact (just send mail, Clio responds)
3. Admin commands (list, waiting, status, whitelist, blacklist, onboarding, prompt, language, help, manual)
4. The #kodord system for project context in /prompt
5. Language preferences (per contact, stored, changeable)
6. Whitelist / blacklist flow
7. Approval flow (JA/NEJ)
8. Interview dialog: "intervju start" (body: till:/ämne:/context) and "intervju stopp" (body: email).
   Clio sends opening question, reads full thread history, generates one question at a time.
Format: clear sections with headers, plain text suitable for email.
Max 70 lines."""
    response = client.messages.create(
        model=MODEL, max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    return CommandResult(response.content[0].text.strip())


def _cmd_language(mail_item, config) -> CommandResult:
    """Byter språkpreferens för adminen."""
    sender_email = re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", mail_item.sender or "")
    if not sender_email:
        return CommandResult("Could not determine your email address.")
    sender_email = sender_email.group(0).lower()

    body = mail_item.body.strip().lower()
    lang_match = re.search(r"\b([a-z]{2})\b", body)
    if not lang_match:
        return CommandResult("Usage: subject=language, body=<code>  (e.g. sv, en, fr, de)")
    lang = lang_match.group(1)

    state.upsert_partner(sender_email, language=lang)
    return CommandResult(f"Language preference updated to '{lang}' for {sender_email}.")


def _cmd_onboarding(mail_item, config) -> CommandResult:
    """Skickar välkomstmail till ny kontakt."""
    recipient_email, rest = _parse_first_email(mail_item.body)
    if not recipient_email:
        return CommandResult(
            "Usage: subject=onboarding, body=email@example.com  [optional name]"
        )

    # Namn: första raden av rest om den inte ser ut som en adress
    name_line = rest.splitlines()[0].strip() if rest else ""
    name = name_line if name_line and "@" not in name_line else ""

    # Spara/uppdatera partner
    lang = _detect_language(recipient_email, config)
    state.upsert_partner(
        recipient_email,
        name=name or None,
        language=lang,
        role="contact",
        onboarded_at=datetime.utcnow().isoformat(),
    )

    # Generera välkomstmail
    from reply import _get_client, MODEL
    client = _get_client()
    greeting = f"Dear {name}" if name else "Hello"
    prompt = f"""{greeting},

Write a warm onboarding email for a contact who will interact with Clio,
an AI assistant at Arvas International AB.
Language: {lang}
Include:
- First line ALWAYS in English: "Reply with 'language <code>' (e.g. 'language en') to change language. Send 'help' for available commands."
- What Clio is (AI assistant, handles mail, responds on behalf of Arvas)
- How to reach Clio (just send mail to clio@arvas.international)
- That a human (Fredrik at Arvas) oversees responses
- Tone: professional, warm, concise
Max 20 lines. No bullet points in first paragraph."""
    response = client.messages.create(
        model=MODEL, max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    onboarding_body = response.content[0].text.strip()

    outbound = OutboundMail(
        to_addr=recipient_email,
        subject="Welcome to Clio — Arvas International",
        body=onboarding_body,
        from_account_key="clio",
    )
    return CommandResult(
        f"Onboarding mail sent to {recipient_email} (language: {lang}).",
        outbound=[outbound],
    )


def _cmd_prompt(mail_item, config) -> CommandResult:
    """
    Skickar ett instruktionsmail till en tredje part.
    Body: rad 1 = mottagarens e-post, resten = instruktion med #kodord.

    Flöde:
      1. Parsa mottagare + instruktion
      2. Extrahera #kodord → hämta NCCs
      3. Om inga #kodord → svar med resonemang (is_reasoning=True)
      4. Om oklart primärt NCC → fråga
      5. Annars → generera mail + skicka
    """
    recipient_email, instruction = _parse_first_email(mail_item.body)
    if not recipient_email:
        return CommandResult(
            "Usage: subject=prompt, body=\nemail@recipient.com\nInstruction with #kodord for context.",
            is_reasoning=True,
        )

    if not instruction:
        return CommandResult(
            f"Recipient: {recipient_email}\n\n"
            "Missing instruction. Add your message after the email address.\n"
            "Use #kodord to attach project context (e.g. #ssf, #iaf).",
            is_reasoning=True,
        )

    # Hämta avsändarens tillåtna kodord-scope (user-nivå)
    from classifier import extract_sender_email
    from clio_access import AccessManager
    from helpers import _account_key_for
    _sender = extract_sender_email(mail_item.sender)
    _am = AccessManager.from_config(config)
    _user_scope = _am.get_kodord_scope({"email": _sender})

    # Hämta brevlådans kodord-scope
    _account_key = _account_key_for(mail_item.account, config)
    _account_scope = notion_client.load_account_scope(_account_key)

    # Effektivt scope = restriktivast av user-scope och account-scope
    if _user_scope is None:
        _allowed = _account_scope
    elif _account_scope is None:
        _allowed = _user_scope
    else:
        _allowed = [k for k in _user_scope if k in _account_scope]

    # Extrahera #kodord
    kodord_list = _parse_kodord(instruction)

    # Kontrollera mot brevlådans scope — explicit fel om out-of-scope
    if _account_scope is not None and kodord_list:
        out_of_scope = [k for k in kodord_list if k not in _account_scope]
        if out_of_scope:
            return CommandResult(
                f"Kodordet {', '.join('#' + k for k in out_of_scope)} hanteras inte av "
                f"denna brevlåda ({_account_key}@). Kontakta Fredrik.",
                is_reasoning=True,
            )

    matched_projs, not_found = _resolve_nccs(kodord_list, config, allowed_kodord=_allowed) if kodord_list else ([], [])

    # Inget #kodord alls → be om förtydligande
    if not kodord_list:
        return CommandResult(
            f"Recipient: {recipient_email}\n\n"
            f"No #kodord found in your instruction. I can't identify which project(s) to use as context.\n\n"
            f"Please resend with one or more #kodord, e.g.:\n"
            f"  #ssf  — SSF-ansökan\n"
            f"  #iaf  — IAF\n\n"
            f"Send 'list' to see all available #kodord.",
            is_reasoning=True,
        )

    # Okänt kodord → uppmärksamma men fortsätt om minst ett är känt
    if not_found and not matched_projs:
        return CommandResult(
            f"Unknown #kodord: {', '.join('#' + k for k in not_found)}\n\n"
            f"Send 'list' to see all valid kodord.",
            is_reasoning=True,
        )

    # Bygg kontext: primär = första matchningen, sekundära = resten
    primary = matched_projs[0]
    secondary = matched_projs[1:]

    context_parts = []
    primary_text = _fetch_ncc_text(primary)
    if primary_text:
        context_parts.append(f"PRIMARY CONTEXT — {primary['name']}:\n{primary_text}")
    for sec in secondary:
        sec_text = _fetch_ncc_text(sec)
        if sec_text:
            context_parts.append(f"SECONDARY CONTEXT — {sec['name']}:\n{sec_text}")

    context_block = "\n\n---\n\n".join(context_parts)

    # Detektera mottagarens språk
    recipient_lang = _detect_language(recipient_email, config)

    # Generera mailet
    from reply import _get_client, MODEL
    client = _get_client()

    not_found_note = (
        f"\nNote: #kodord not found (ignored): {', '.join(not_found)}"
        if not_found else ""
    )

    prompt = f"""You are Clio, AI assistant at Arvas International AB.
An admin has asked you to send a professional instruction email to a contact.

Recipient: {recipient_email}
Language to use: {recipient_lang}
Admin's instruction: {instruction}
{not_found_note}

Project context:
{context_block or '(no context cards available for matched projects)'}

Write a clear, professional email in {recipient_lang}.
- Be specific and action-oriented
- Reference the project naturally if relevant
- Do not reveal that this is AI-generated
- Do not add a subject line (it will be added separately)
- Sign as: Clio / Arvas International"""

    response = client.messages.create(
        model=MODEL, max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    email_body = response.content[0].text.strip()

    proj_names = " + ".join(p["name"] for p in matched_projs)
    subject = f"{primary['name']} — {instruction[:40].rstrip()}"

    outbound = OutboundMail(
        to_addr=recipient_email,
        subject=subject,
        body=email_body,
        from_account_key="clio",
    )

    # Bekräftelse till admin
    sec_note = (f"\nSecondary context: {', '.join('#' + p['kodord'] for p in secondary)}"
                if secondary else "")
    nf_note  = (f"\nIgnored (not found): {', '.join('#' + k for k in not_found)}"
                if not_found else "")
    confirm = (
        f"Prompt sent to {recipient_email}\n"
        f"Primary context: #{primary['kodord']} ({primary['name']})"
        f"{sec_note}{nf_note}\n\n"
        f"Subject: {subject}\n\n"
        f"─── Message ───\n{email_body}"
    )
    return CommandResult(confirm, outbound=[outbound])


# ── NCC-kommandon ─────────────────────────────────────────────────────────────

def _cmd_ncc_lista(mail_item, config) -> CommandResult:
    """
    Hierarkisk projektlista: Sfär → Projekt (2.x) → Metod (2.x.y).
    Rader med Nr X.Y.Z indenteras under X.Y.
    """
    from collections import defaultdict

    raw = config.get("mail", "knowledge_notion_db_ids", fallback="")
    db_entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not db_entries:
        return CommandResult("Ingen projektdatabas konfigurerad.")

    db_id = db_entries[0].split(":")[0].strip()
    index = notion_client.get_project_index_full(db_id)
    if not index:
        return CommandResult("Projektlistan är tom eller otillgänglig.")

    def sort_key(p):
        nr = p.get("nr") or "999"
        try:
            return [int(x) for x in nr.split(".")]
        except ValueError:
            return [999]

    index.sort(key=sort_key)

    by_sfar = defaultdict(list)
    for proj in index:
        by_sfar[proj.get("sfar") or "Övrigt"].append(proj)

    SFAR_ORDER = ["Familj", "Fredrik", "Ulrika", "AIAB", "Capgemini", "GSF", "Övrigt"]
    SFAR_ICONS = {
        "Familj": "🏠", "Fredrik": "👤", "Ulrika": "👤",
        "AIAB": "🏢", "Capgemini": "💼", "GSF": "⛳", "Övrigt": "📁",
    }
    STATUS_EMOJI = {
        "✅ Bekräftad": "✅", "✅ Trolig": "✅",
        "⚠️ Osäker": "⚠️", "❌ Saknas": "❌",
        "🔵 Inget projekt": "🔵",
    }

    sep = "━" * 44
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📋 PROJEKTMASTERLISTAN — {now}", ""]

    total    = len(index)
    with_ncc = sum(1 for p in index if p.get("ncc_url"))

    for sfar in SFAR_ORDER:
        projs = by_sfar.get(sfar)
        if not projs:
            continue
        lines += [sep, f"{SFAR_ICONS.get(sfar, '📁')} {sfar.upper()}", sep]
        for proj in projs:
            nr     = proj.get("nr") or ""
            kodord = proj.get("kodord") or ""
            name   = proj.get("name") or ""
            status = proj.get("status") or ""
            depth  = max(0, len(nr.split(".")) - 2) if nr else 0
            indent = "     " * depth
            emoji  = STATUS_EMOJI.get(status, "❓")
            lines.append(
                f"{indent}{nr:<7} {'#'+kodord:<15} {name[:30]:<30} {emoji}"
            )
        lines.append("")

    lines += [
        sep,
        f"Totalt: {total} | Med NCC: {with_ncc} | Saknar: {total - with_ncc}",
        "",
        "SKAPA NY — ämne: nytt ncc",
        "  Kodord: [kodord]  Namn: [namn]  Sfär: [sfär]",
        "  Nr: [2.x.y]  Förälder: [kodord]  Beskrivning: [text]",
    ]
    return CommandResult("\n".join(lines))


def _cmd_ncc_ny(mail_item, config) -> CommandResult:
    """
    Skapar NCC i Notion + masterlistrad + synkblock-uppdatering.

    Mail-format (brödtext):
        Kodord: retorik
        Namn: Retorikcoachen
        Sfär: Fredrik
        Nr: 2.2.3             (valfritt)
        Förälder: cliocoach   (valfritt)
        Beskrivning: ...      (valfritt)
    """
    body = mail_item.body.strip()

    def _field(text, *keys):
        for key in keys:
            m = re.search(rf"(?i)^{key}\s*:\s*(.+)$", text, re.MULTILINE)
            if m:
                return m.group(1).strip()
        return ""

    kodord      = _field(body, "kodord", "keyword", "kod").lower()
    namn        = _field(body, "namn", "name", "projektnamn")
    sfar        = _field(body, "sfär", "sfar", "sphere") or "Fredrik"
    nr          = _field(body, "nr", "nummer", "number")
    foralder_kw = _field(body, "förälder", "foralder", "parent").lower()
    beskrivning = _field(body, "beskrivning", "description", "desc")

    if not kodord:
        return CommandResult(
            "Saknar Kodord.\n\nFormat:\n"
            "  Kodord: [kodord]\n  Namn: [namn]\n  Sfär: [Fredrik/Ulrika/...]\n"
            "  Nr: [t.ex. 2.2.6]  (valfritt)\n  Förälder: [kodord]  (valfritt)",
            is_reasoning=True,
        )
    if not namn:
        return CommandResult(
            f"Saknar Namn för kodord '{kodord}'.", is_reasoning=True,
        )

    raw = config.get("mail", "knowledge_notion_db_ids", fallback="")
    db_entries = [e.strip() for e in raw.split(",") if e.strip()]
    db_id = db_entries[0].split(":")[0].strip() if db_entries else ""
    index = notion_client.get_project_index_full(db_id) if db_id else []

    # Dublettkoll
    existing = next((p for p in index if p.get("kodord") == kodord), None)
    if existing:
        return CommandResult(
            f"⚠️ Kodord '#{kodord}' finns redan: {existing['name']}\n"
            f"NCC: {existing.get('ncc_url', '(ingen)')}\n"
            f"Uppdatera direkt i Notion vid behov.",
            is_reasoning=True,
        )

    # Förälderns page_id
    SYNC_SPEC_PAGE = "33d67666d98a81368c12fab463b95de1"
    parent_page_id = "33467666d98a816db2c0d30cb97206a3"  # Mall & Projektöversikt
    if foralder_kw:
        pp = next((p for p in index if p.get("kodord") == foralder_kw), None)
        if pp and pp.get("ncc_page_id"):
            parent_page_id = pp["ncc_page_id"]
        else:
            logger.warning(f"[ncc_ny] Förälder '#{foralder_kw}' ej hittad — använder default-förälder")

    # Skapa NCC-sida
    now_str = datetime.utcnow().strftime("%Y-%m-%d")
    content = (
        f"## 🔧 {namn} — NCC\n"
        f"Senast uppdaterad: {now_str}\n"
        f"Status: ❌ Ej byggd — platshållare\n\n"
        f"För Clio: NCC:n är inte färdig. Om du ropar in #{kodord}, "
        f"meddela att metoden är under uppbyggnad.\n\n"
        f"## Vad ska den täcka\n"
        f"{beskrivning or '(saknas — lägg till manuellt)'}\n\n"
        f"## Versionslogg\n"
        f"| Version | Datum | Förändring |\n"
        f"|---|---|---|\n"
        f"| 0.1 | {now_str} | Platshållare skapad via clio-mail-agent |"
    )
    ncc_page_id, ncc_url = notion_client.create_ncc_page(
        parent_page_id=parent_page_id,
        title=f"🔧 {namn} — NCC",
        content=content,
    )
    if not ncc_page_id:
        return CommandResult("❌ Kunde inte skapa NCC-sidan i Notion.")

    # Masterlistrad
    notion_client.create_masterlist_row(
        db_page_id="c4d630a1252d4d7fb73cd65535c07708",
        projektnamn=namn,
        kodord=kodord,
        nr=nr or None,
        sfar=sfar,
        status="❌ Saknas",
        ncc_url=ncc_url,
        ncc_namn=f"{namn} — NCC",
    )

    # Synkblock (best-effort)
    notion_client.append_kodord_to_sync_spec(
        page_id=SYNC_SPEC_PAGE,
        kodord=kodord,
        ncc_page_id=ncc_page_id,
    )

    # Svar = bekräftelse + aktuell lista
    lista = _cmd_ncc_lista(mail_item, config)
    confirm = (
        f"✅ NCC skapad!\n\n"
        f"  Kodord:   #{kodord}\n"
        f"  Namn:     {namn}\n"
        f"  Sfär:     {sfar}\n"
        f"  Nr:       {nr or '(ej satt)'}\n"
        f"  Förälder: {'#' + foralder_kw if foralder_kw else '(ingen)'}\n"
        f"  Notion:   {ncc_url}\n\n"
        f"Synkblocket uppdaterat — synka CLAUDE.md manuellt vid behov.\n\n"
        f"{'─' * 44}\n\n{lista.reply_body}"
    )
    return CommandResult(confirm)


# ── Sprint 3: obit import ─────────────────────────────────────────────────────

def _cmd_obit_import(mail_item, config) -> CommandResult:
    """
    Handles ACTION_OBIT_IMPORT: imports a returned [clio-obit] CSV watch list.

    Flow:
      1. Find the first .csv attachment on the mail item
      2. Save it to a temp file
      3. Call clio-agent-obit/watchlist/import_email.run(csv, owner)
      4. Return receipt text (sent back to sender by main.py)
    """
    import os
    import sys
    import tempfile

    sender_email = extract_sender_email(mail_item.sender or "")

    # Find CSV attachment — attachments are saved to disk by imap_client before
    # commands are dispatched, so mail_item.attachments contains filepath info.
    csv_path: str | None = None
    for att in getattr(mail_item, "attachments", []):
        fname = getattr(att, "filename", "") or ""
        fpath = getattr(att, "filepath", "") or getattr(att, "path", "") or ""
        if fname.lower().endswith(".csv") and fpath:
            csv_path = fpath
            break

    if not csv_path or not os.path.exists(csv_path):
        return CommandResult(
            "Kunde inte hitta CSV-bilagan i ditt mail.\n"
            "Kontrollera att filen är bifogad med .csv-ändelse och försök igen."
        )

    # Delegate to clio-agent-obit's import logic
    _OBIT_WATCHLIST = os.path.join(
        os.path.dirname(__file__), "..", "clio-agent-obit", "watchlist"
    )
    sys.path.insert(0, _OBIT_WATCHLIST)
    try:
        import import_email as _obit_import
        success, receipt = _obit_import.run(csv_path, sender_email)
    except ImportError as e:
        logger.error(f"[obit_import] Could not import import_email: {e}")
        return CommandResult(
            "Tekniskt fel: clio-agent-obit/watchlist/import_email.py hittades inte.\n"
            "Kontakta Fredrik."
        )
    finally:
        if _OBIT_WATCHLIST in sys.path:
            sys.path.remove(_OBIT_WATCHLIST)

    if not success:
        logger.warning(f"[obit_import] Import rejected for {sender_email}: {receipt}")
        return CommandResult(receipt)

    logger.info(f"[obit_import] Import OK for {sender_email}")
    return CommandResult(receipt)


def _cmd_update(mail_item, config) -> CommandResult:
    """
    Appendar brödtexten till ett projekts context card i Notion.

    Kräver att avsändaren har :rw-behörighet på det angivna kodordet.
    Kommandot är dolt — visas bara i /manual för behöriga användare.

    Ämne: update #kodord
    Brödtext: text att lägga till i context card-sidan
    """
    from classifier import extract_sender_email
    from clio_access import AccessManager

    sender_email = extract_sender_email(mail_item.sender)
    am = AccessManager.from_config(config)
    write_scope = am.get_kodord_write_scope({"email": sender_email})

    # Extrahera #kodord ur ämnesraden
    kodord_list = _parse_kodord(mail_item.subject)
    if not kodord_list:
        return CommandResult(
            "Inget #kodord angivet i ämnesraden.\n"
            "Exempel: update #capssf",
            is_reasoning=True,
        )

    # Kontrollera behörighet
    if write_scope is not None:
        unauthorized = [k for k in kodord_list if k not in write_scope]
        if unauthorized:
            return CommandResult(
                f"Du har inte skrivbehörighet för: {', '.join('#' + k for k in unauthorized)}\n"
                "Kontakta Fredrik om du behöver skrivåtkomst.",
                is_reasoning=True,
            )

    # Slå upp projektet
    matched, not_found = _resolve_nccs(kodord_list, config, allowed_kodord=write_scope)
    if not matched:
        unknown = ', '.join('#' + k for k in not_found)
        return CommandResult(
            f"Okänt kodord: {unknown}\n"
            "Skicka 'list' för att se tillgängliga kodord.",
            is_reasoning=True,
        )

    body_text = (mail_item.body or "").strip()
    if not body_text:
        return CommandResult(
            "Brödtexten är tom — inget att lägga till.",
            is_reasoning=True,
        )

    # Uppdatera varje matchat projekt
    updated = []
    notify_lines = []
    for proj in matched:
        page_id = proj.get("page_id", "")
        if not page_id:
            continue
        notion_client.append_to_context_card(page_id, body_text, author=sender_email)
        updated.append(proj["name"])
        preview = body_text[:200] + ("…" if len(body_text) > 200 else "")
        notify_lines.append(
            f"#{proj['kodord']} — {proj['name']}\n{preview}"
        )

    if not updated:
        return CommandResult(
            "Hittade inga context cards att uppdatera (saknar page_id).",
            is_reasoning=True,
        )

    # Avisering till Fredrik
    notify_addr = config.get("mail", "notify_address", fallback="")
    outbound = []
    if notify_addr:
        notify_body = (
            f"Context card uppdaterat av {sender_email}:\n\n"
            + "\n\n---\n\n".join(notify_lines)
        )
        outbound.append(OutboundMail(
            to_addr=notify_addr,
            subject=f"[CLIO-INFO] Context card uppdaterat: {', '.join('#' + p['kodord'] for p in matched)}",
            body=notify_body,
            from_account_key="clio",
        ))

    names = ", ".join(updated)
    return CommandResult(
        f"Context card uppdaterat för: {names}\nTack!",
        outbound=outbound,
    )


# ── Intervjukommandon ─────────────────────────────────────────────────────────

def _cmd_interview_start(mail_item, config) -> CommandResult:
    """
    Startar en intervjusekvens.

    Brödtext-format:
      till: frippe@capgemini.com
      ämne: Karriärsamtal Q2 2026
      [valfri kontext / öppningsfråga]
    """
    import uuid as _uuid
    import reply as reply_module
    import smtp_client as smtp_module

    body = mail_item.body or ""
    to_addr = None
    subject = "Intervju"
    context_lines = []

    for line in body.splitlines():
        l = line.strip()
        if l.lower().startswith("till:"):
            to_addr = l.split(":", 1)[1].strip()
        elif l.lower().startswith("ämne:") or l.lower().startswith("subject:"):
            subject = l.split(":", 1)[1].strip()
        elif l:
            context_lines.append(l)

    if not to_addr:
        return CommandResult(
            "Intervju kunde inte startas — saknar 'till: adress' i brödtexten.\n\n"
            "Format:\n  till: namn@exempel.se\n  ämne: Valfritt ämne\n  [kontext]"
        )

    context = "\n".join(context_lines)
    thread_id = f"<clio-interview-{_uuid.uuid4()}@arvas.international>"
    opener = reply_module.generate_interview_opener(subject, context, config)

    account_key = "clio"
    out_msg_id  = f"<clio-interview-{_uuid.uuid4()}@arvas.international>"
    outbound = [OutboundMail(
        from_account_key=account_key,
        to_addr=to_addr,
        subject=subject,
        body=opener,
        message_id=out_msg_id,
    )]

    # Spara session + utgående mail
    state.create_interview_session(thread_id, to_addr, account_key=account_key)
    state.save_outbound_interview_reply(
        thread_id=thread_id,
        account=config.get("mail", f"imap_user_{account_key}", fallback=account_key),
        sender=config.get("mail", f"imap_user_{account_key}", fallback="clio@arvas.international"),
        subject=subject,
        body=opener,
        message_id=out_msg_id,
    )

    logger.info(f"[interview_start] Session skapad för {to_addr} (tråd: {thread_id[:30]}…)")
    return CommandResult(
        f"Intervju startad med {to_addr}.\nÄmne: {subject}\n\nÖppningsmail skickat.",
        outbound=outbound,
    )


def _cmd_interview_stop(mail_item, config) -> CommandResult:
    """
    Avslutar en pågående intervjusession.
    Brödtext: e-postadress till deltagaren.
    """
    body = (mail_item.body or "").strip()
    participant = body.splitlines()[0].strip() if body else ""

    if not participant or "@" not in participant:
        return CommandResult(
            "Ange deltagarens e-postadress i brödtexten."
        )

    session = state.get_active_interview(participant)
    if not session:
        return CommandResult(f"Ingen aktiv intervjusession hittades för {participant}.")

    state.stop_interview_session(session["thread_id"])
    logger.info(f"[interview_stop] Session avslutad för {participant}")
    return CommandResult(f"Intervjusession med {participant} avslutad.")


# ── Dispatch ──────────────────────────────────────────────────────────────────

_HANDLERS = {
    "list":        _cmd_list,
    "waiting":     _cmd_waiting,
    "status":      _cmd_status,
    "whitelist":   _cmd_whitelist,
    "blacklist":   _cmd_blacklist,
    "help":        _cmd_help,
    "adminhelp":   _cmd_adminhelp,
    "manual":      _cmd_manual,
    "language":    _cmd_language,
    "onboarding":  _cmd_onboarding,
    "prompt":      _cmd_prompt,
    "update":      _cmd_update,         # Dolt — skrivrätt per kodord (:rw)
    "obit_import": _cmd_obit_import,   # Sprint 3 — routed by ACTION_OBIT_IMPORT
    "ncc_ny":           _cmd_ncc_ny,
    "ncc_lista":        _cmd_ncc_lista,
    "interview_start":  _cmd_interview_start,
    "interview_stop":   _cmd_interview_stop,
}


def dispatch(command: str, mail_item, config) -> CommandResult:
    """Kör kommandohanteraren och returnerar CommandResult."""
    handler = _HANDLERS.get(command)
    if not handler:
        return CommandResult(f"Unknown command: {command}")
    try:
        return handler(mail_item, config)
    except Exception as e:
        logger.error(f"Command '{command}' failed: {e}", exc_info=True)
        return CommandResult(f"Command '{command}' failed: {e}")


def _cmd_waiting_decide(mail_item, config) -> CommandResult:
    """Godkänn ett väntande mail direkt från Odoo admin.

    subject = action: VITLISTA | SVARTLISTA | BEHÅLL
    body    = avsändarens e-postadress
    """
    import re as _re

    action = (mail_item.subject or "").strip().upper()
    body   = (mail_item.body or "").strip()

    email_match = _re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", body)
    if not email_match:
        return CommandResult("Saknar e-postadress i brödtexten.")
    sender = email_match.group(0).lower()

    valid = ("VITLISTA", "SVARTLISTA", "BEHÅLL")
    if action not in valid:
        return CommandResult(
            f"Okänd action: {action!r}. Använd VITLISTA, SVARTLISTA eller BEHÅLL."
        )

    if action == "VITLISTA":
        import handlers as _handlers
        wl_page = config.get("mail", "whitelist_notion_page_id", fallback="")
        if wl_page:
            from notion_client import add_to_whitelist
            add_to_whitelist(wl_page, sender)
        state.upsert_partner(sender, role="contact")
        _handlers._process_waiting_mails(sender, config)
        return CommandResult(f"Vitlistad och väntande mail bearbetade: {sender}")

    if action == "SVARTLISTA":
        state.add_to_blacklist(sender)
        with state.get_connection() as conn:
            conn.execute(
                "UPDATE mail SET status = ? WHERE sender LIKE ? AND status = ?",
                (state.STATUS_REJECTED, f"%{sender}%", state.STATUS_WAITING),
            )
        return CommandResult(f"Svartlistad: {sender}")

    # BEHÅLL
    import handlers as _handlers
    _handlers._send_standard_for_waiting(sender, config)
    return CommandResult(f"Standardsvar skickat för: {sender}")
