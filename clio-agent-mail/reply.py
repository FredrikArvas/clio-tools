"""
reply.py — svarsgenerering via Claude Sonnet för clio@arvas.international
"""
import os
import logging
import sys
from pathlib import Path

from clio_core.utils import t, set_language

import anthropic
import attachments as att_module

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5"

SIGNATURE = """Med vänliga hälsningar
Clio
Arvas International AB

Clio är Arvas Internationals AI-medarbetare."""


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(t("mail_missing_api_key"))
    return anthropic.Anthropic(api_key=api_key)


def _format_examples(examples: list) -> str:
    """Formaterar godkända läroexempel för injektion i prompten."""
    if not examples:
        return ""
    lines = ["## Tidigare godkända svar (Fredriks ton och stil)"]
    for i, ex in enumerate(examples[:5], 1):
        subj = ex["original_subject"] or t("email_no_subject")
        lines.append(f"\n### Exempel {i} — {subj[:60]}")
        lines.append(f"{ex['approved_reply'][:600]}")
    return "\n".join(lines)


def _build_attachment_content(mail_item) -> tuple[str, list]:
    """
    Extraherar bilagor och returnerar:
      - text_section : str  (text att injicera i prompten)
      - image_blocks : list (Claude-innehållsblock för bilder)
    """
    if not mail_item.attachments:
        return "", []

    text_parts = []
    image_blocks = []

    for meta in mail_item.attachments:
        result = att_module.extract(meta.filepath)

        if result.error:
            text_parts.append(f"[Bilaga: {meta.filename} — kunde inte läsas: {result.error}]")
        elif result.image_b64:
            text_parts.append(f"[Bilaga: {meta.filename} — bild, visas nedan]")
            image_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": result.image_media_type,
                    "data": result.image_b64,
                },
            })
        elif result.text:
            text_parts.append(
                f"[Bilaga: {meta.filename}]\n{result.text}"
            )
        else:
            text_parts.append(f"[Bilaga: {meta.filename} — tomt innehåll]")

    text_section = ""
    if text_parts:
        text_section = "\n## Bilagor\n\n" + "\n\n---\n\n".join(text_parts)

    return text_section, image_blocks


def generate_reply(mail_item, context: str, config, knowledge: str = "",
                   examples: list = None) -> str:
    """
    Genererar ett svar på ett mail till clio@arvas.international.

    mail_item : MailItem
    context   : extra instruktion till Claude (t.ex. om [CLIO-AUTO] eller draft-läge)
    config    : ConfigParser
    knowledge : aktuell kunskapsbas hämtad från Notion (injiceras i prompten)
    """
    knowledge_section = f"\n{knowledge}\n" if knowledge else ""
    examples_section = f"\n{_format_examples(examples)}\n" if examples else ""
    attachment_text, image_blocks = _build_attachment_content(mail_item)

    prompt_text = f"""Du är Clio, AI-medarbetare på Arvas International AB.
Du svarar på ett mail till clio@arvas.international.

{context}
{knowledge_section}{examples_section}
Inkommande mail:
Från: {mail_item.sender}
Ämne: {mail_item.subject}
Meddelande:
{mail_item.body}
{attachment_text}
Skriv ett professionellt, personligt och hjälpsamt svar på svenska.
Var direkt och konkret. Matcha tonen i det inkommande mailet.
Använd endast information från kunskapsbasen ovan — hitta aldrig på fakta.
Låt de tidigare godkända svaren guida din ton och struktur.
Om bilagor finns — referera till relevant innehåll i ditt svar.

Avsluta alltid med denna signatur, exakt som den är:

{SIGNATURE}"""

    # Bygg content-lista: text + eventuella bilder (Claude vision)
    content: list = [{"type": "text", "text": prompt_text}]
    content.extend(image_blocks)

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text.strip()


def generate_holding_reply_for_unknown(mail_item, config) -> str:
    """
    Kort bekräftelsesvar till okänd avsändare.
    Informerar om att de kommer att höras av — avslöjar inte systemets natur.
    """
    prompt = f"""Du är Clio, AI-medarbetare på Arvas International AB.

Du har fått ett mail från en avsändare som inte finns i systemet ännu.
Skriv ett kort, varmt bekräftelsesvar på svenska (2–3 meningar) som:
- Bekräftar att mailet tagits emot
- Informerar om att de kommer att höra av sig inom kort
- Inte avslöjar att det är ett automatiserat system (signaturen hanterar det)

Från: {mail_item.sender}
Ämne: {mail_item.subject}

Avsluta med denna signatur, exakt som den är:

{SIGNATURE}"""

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def generate_self_query_reply(mail_item, config, knowledge: str = "") -> str:
    """
    Svarar på en direkt fråga från Fredrik.
    Använder kunskapsbasen men är mer informell och direkt än externa svar.
    """
    knowledge_section = f"\n{knowledge}\n" if knowledge else ""
    prompt = f"""Du är Clio, AI-medarbetare på Arvas International AB.
Fredrik (din kollega och uppdragsgivare) mailar dig direkt med en fråga eller ett uppdrag.
Svara direkt och hjälpsamt på svenska. Var konkret. Du behöver inte vara formell.
Använd kunskapsbasen nedan om den är relevant.
{knowledge_section}
Fråga från Fredrik:
Ämne: {mail_item.subject}
{mail_item.body}

Svara ovanför strecket — ingen signatur behövs."""

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def generate_interview_reply(mail_item, thread_history: list,
                             system_prompt: str, config) -> str:
    """
    Genererar nästa fråga i en intervjudialog.

    thread_history : lista av dict {direction, sender, body} — kronologisk ordning
    system_prompt  : intervjupersonans instruktion
    """
    messages = []
    for turn in thread_history:
        role = "assistant" if turn["direction"] == "outbound" else "user"
        messages.append({"role": role, "content": turn["body"] or ""})

    # Nuvarande inkommande svar (om det inte redan finns i historiken)
    if not thread_history or thread_history[-1]["direction"] != "inbound":
        messages.append({"role": "user", "content": mail_item.body or ""})

    # Garantera att vi börjar med user (Claude-krav)
    if messages and messages[0]["role"] == "assistant":
        messages.insert(0, {"role": "user", "content": "[Intervjun startar]"})

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text.strip()


def generate_interview_opener(subject: str, context: str, config) -> str:
    """Genererar det första mailet i en intervjusekvens (ingen historik ännu)."""
    prompt = f"""Du är Clio, AI-medarbetare på Arvas International AB, och startar en strukturerad intervjudialog.

{context}

Skriv ett välkomnande, varmt öppningsmail som:
- Presenterar syftet med intervjun kort (1–2 meningar)
- Ställer den FÖRSTA frågan — en enda, öppen fråga
- Inte avslöjar att det är ett automatiserat system (signaturen hanterar det)
- Använder INTE markdown-formattering (inga **fetstil**, inga rubriker med #, ingen ämnesrad överst)
- Börjar direkt med "Hej [förnamn]," — ingen inledande ämnesrad

Ämne för intervjun: {subject}

Avsluta med denna signatur, exakt som den är:

{SIGNATURE}"""
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def generate_standard_reply(mail_item, config) -> str:
    """
    Standardsvar för ej vitlistade avsändare till clio@.
    Hänvisar till info@ utan att avslöja systemets natur.
    """
    prompt = f"""Du är Clio, AI-medarbetare på Arvas International AB.

Du har fått ett mail till clio@arvas.international från en okänd avsändare.
Denna adress är reserverad för interna och auktoriserade kontakter.

Inkommande mail:
Från: {mail_item.sender}
Ämne: {mail_item.subject}

Skriv ett kort, artigt svar på svenska (max 3 meningar) som:
- Bekräftar att mailet mottagits
- Hänvisar till info@arvas.international för allmänna förfrågningar
- Inte avslöjar att det är ett automatiserat system (signaturen hanterar det)

Avsluta med denna signatur, exakt som den är:

{SIGNATURE}"""

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()
