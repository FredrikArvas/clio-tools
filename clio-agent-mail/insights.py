"""
insights.py — periodisk analys och förutsägelse av kommande frågor

Läser state.db, skickar till Claude och sparar insikterna till Notion.
Kan anropas manuellt via clio.py-menyn eller schemaläggas.
"""
import os
import logging
from datetime import datetime

import anthropic

import state
import notion_data

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5"


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY saknas i miljövariabler")
    return anthropic.Anthropic(api_key=api_key)


def generate_insights(config) -> str:
    """
    Analyserar alla hanterade mail och genererar insikter + förutsägelser.
    Returnerar insiktstexten som sträng.
    """
    rows = state.get_all_mail_for_insights(limit=200)
    if not rows:
        return "Inga mail att analysera ännu."

    learned = state.get_learned_replies(limit=50)

    mail_summary = "\n".join(
        f"- [{r['action']}] Från: {r['sender'][:40]} | Ämne: {r['subject'][:60]} | Status: {r['status']}"
        for r in rows
    )

    learned_summary = ""
    if learned:
        learned_summary = (
            f"\n\nGodkända svar (Fredrik har sagt JA på {len(learned)} utkast):\n"
            + "\n".join(f"- {ex['original_subject'][:60]}" for ex in learned)
        )

    prompt = f"""Du är Clio, AI-medarbetare på Arvas International AB.

Nedan är en sammanställning av {len(rows)} mail som hanterats:

{mail_summary}
{learned_summary}

Analysera mönstren och leverera en strukturerad rapport på svenska med följande sektioner:

## 1. Mönster och trender
Vad är de vanligaste ämnena och frågorna? Vilka avsändare är mest aktiva?

## 2. Förutsägelser
Lista 3-5 konkreta frågor som sannolikt kommer att ställas den kommande veckan, baserat på mönstren.

## 3. Rekommendationer
Vad bör läggas till i FAQ? Vilka avsändare bör vitlistas? Finns det mönster som tyder på problem?

Var konkret och basera allt på datan ovan."""

    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def store_insights_to_notion(insights_text: str, config):
    """Sparar insikterna till Notion-sidan konfigurerad i clio.config."""
    page_id = config.get("mail", "insights_notion_page_id", fallback="").strip()
    if not page_id:
        logger.warning("insights_notion_page_id saknas i clio.config — insikter sparas inte till Notion")
        return

    try:
        client = notion_data._get_client()
        today = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        client.blocks.children.append(
            block_id=page_id,
            children=[
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": f"Analys {today}"}}]
                    },
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": insights_text}}]
                    },
                },
                {
                    "object": "block",
                    "type": "divider",
                    "divider": {},
                },
            ],
        )
        logger.info(f"Insikter sparade till Notion-sida: {page_id}")
    except Exception as e:
        logger.error(f"Fel vid sparande av insikter till Notion: {e}")


def run_insights(config, save_to_notion: bool = True) -> str:
    """
    Huvudfunktion: generera insikter och spara till Notion.
    Returnerar insiktstexten (för visning i TUI).
    """
    logger.info("Insiktsanalys startar...")
    text = generate_insights(config)
    if save_to_notion:
        store_insights_to_notion(text, config)
    logger.info("Insiktsanalys klar.")
    return text
