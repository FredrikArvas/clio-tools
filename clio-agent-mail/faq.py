"""
faq.py — FAQ-matchning och svarsgenerering för info@arvas.international

Använder Claude Sonnet för:
  1. Semantisk matchning av inkommande mail mot FAQ-poster
  2. Generering av personligt svar baserat på matchad FAQ-post
  3. Generering av artigt holding-svar vid låg/ingen matchning
"""
import os
import logging
from dataclasses import dataclass

import anthropic

logger = logging.getLogger(__name__)

CONFIDENCE_HIGH = "high"
CONFIDENCE_LOW = "low"
CONFIDENCE_NONE = "none"

MODEL = "claude-sonnet-4-5"

SIGNATURE = """Med vänliga hälsningar
Clio
Arvas International AB

Clio är Arvas Internationals AI-medarbetare."""


@dataclass
class FAQMatch:
    confidence: str      # high / low / none
    question: str        # matchad FAQ-fråga
    answer: str          # matchat FAQ-svar
    explanation: str     # Claudes motivering


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY saknas i miljövariabler")
    return anthropic.Anthropic(api_key=api_key)


def match_faq(mail_item, faq_items: list, config) -> FAQMatch:
    """
    Matchar ett inkommande mail mot FAQ-poster via Claude.
    Returnerar FAQMatch med confidence-nivå.

    mail_item : MailItem
    faq_items : lista av {"question": str, "answer": str}
    config    : ConfigParser
    """
    if not faq_items:
        return FAQMatch(
            confidence=CONFIDENCE_NONE,
            question="",
            answer="",
            explanation="Inga FAQ-poster tillgängliga",
        )

    faq_text = "\n\n".join(
        f"FRÅGA: {item['question']}\nSVAR: {item['answer']}"
        for item in faq_items
    )

    prompt = f"""Du är en assistent som matchar inkommande e-postfrågor mot en FAQ.

FAQ:
{faq_text}

Inkommande mail:
Från: {mail_item.sender}
Ämne: {mail_item.subject}
Meddelande:
{mail_item.body}

Uppgift: Bedöm om detta mail kan besvaras med en av FAQ-posterna ovan.

Svara i exakt detta format (utan extra text):
CONFIDENCE: high|low|none
MATCHED_QUESTION: <exakt FAQ-fråga, eller "ingen" om confidence=none>
EXPLANATION: <en mening om varför>

Regler:
- "high"  = frågan matchar tydligt och FAQ-svaret täcker det avsändaren undrar
- "low"   = delvis matchning men svaret är ofullständigt eller frågan är oklar
- "none"  = ingen matchning eller frågan faller utanför FAQ:n"""

    try:
        client = _get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        return _parse_match_response(text, faq_items)
    except Exception as e:
        logger.error(f"Claude FAQ-matchning misslyckades: {e}")
        return FAQMatch(
            confidence=CONFIDENCE_NONE,
            question="",
            answer="",
            explanation=f"Tekniskt fel vid matchning: {e}",
        )


def _parse_match_response(text: str, faq_items: list) -> FAQMatch:
    """Parsar Claudes strukturerade svar till FAQMatch."""
    parsed = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            parsed[key.strip()] = value.strip()

    confidence = parsed.get("CONFIDENCE", "none").lower()
    matched_q = parsed.get("MATCHED_QUESTION", "")
    explanation = parsed.get("EXPLANATION", "")

    if confidence not in (CONFIDENCE_HIGH, CONFIDENCE_LOW, CONFIDENCE_NONE):
        confidence = CONFIDENCE_NONE

    # Hitta matchande FAQ-post via fallback substring-jämförelse
    for item in faq_items:
        q = item["question"].lower()
        m = matched_q.lower()
        if q in m or m in q:
            return FAQMatch(
                confidence=confidence,
                question=item["question"],
                answer=item["answer"],
                explanation=explanation,
            )

    return FAQMatch(
        confidence=CONFIDENCE_NONE,
        question="",
        answer="",
        explanation=explanation or "Ingen matchning hittad",
    )


def generate_faq_reply(mail_item, faq_match: FAQMatch, config) -> str:
    """
    Genererar ett personligt svar baserat på FAQ-matchning.
    Kallas bara när confidence == high.
    """
    prompt = f"""Du är Clio, AI-medarbetare på Arvas International AB.
Du svarar på ett mail till info@arvas.international.

Inkommande mail:
Från: {mail_item.sender}
Ämne: {mail_item.subject}
Meddelande:
{mail_item.body}

Relevant FAQ-information att basera svaret på:
Fråga: {faq_match.question}
Svar: {faq_match.answer}

Skriv ett personligt, vänligt och kortfattat svar på svenska.
Formulera dig naturligt — kopiera inte FAQ-texten rakt av.
Matcha tonen i det inkommande mailet.

Avsluta alltid med denna signatur, exakt som den är:

{SIGNATURE}"""

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def generate_holding_reply(mail_item, config) -> str:
    """
    Genererar ett artigt 'vi återkommer'-svar för info@
    när FAQ-matchning är låg eller saknas.
    """
    prompt = f"""Du är Clio, AI-medarbetare på Arvas International AB.
Du svarar på ett mail till info@arvas.international.

Inkommande mail:
Från: {mail_item.sender}
Ämne: {mail_item.subject}
Meddelande:
{mail_item.body}

Frågan faller utanför vad du kan besvara direkt.
Skriv ett kort, personligt och vänligt svar på svenska som:
- Bekräftar att mailet tagits emot
- Meddelar att rätt person återkommer med mer information
- Är naturligt och inte robotaktigt
- Är max 3-4 meningar lång

Avsluta alltid med denna signatur, exakt som den är:

{SIGNATURE}"""

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()
