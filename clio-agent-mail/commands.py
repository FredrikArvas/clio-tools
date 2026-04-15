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
}

# Kommandon som kräver admin-behörighet
ADMIN_COMMANDS = {
    "list", "waiting", "status", "whitelist", "blacklist",
    "adminhelp", "manual", "onboarding", "prompt", "language",
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
Format: clear sections with headers, plain text suitable for email.
Max 60 lines."""
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
