"""
clio-vigil — summarizer.py
===========================
Sammanfattar transkriberade bevakningsobjekt via Claude API.

Flöde:
  1. Hämta objekt med state=transcribed och saknat summary
  2. Läs in transkript-JSON (segments med tidsstämplar)
  3. Skicka till Claude med domänspecifik instruktion
  4. Spara summary (2-3 meningar, ~8 ord/mening) i vigil_items.summary
  5. (Ändrar INTE state — summary produceras inför notifier och indexer)

Körning:
  python summarizer.py --run [--domain ufo] [--max 20]
  python summarizer.py --item 42
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from orchestrator import init_db

logger = logging.getLogger(__name__)

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

MAX_TRANSCRIPT_CHARS = 12_000   # ~3 000 tokens — tillräckligt för sammanfattning

# ---------------------------------------------------------------------------
# Promptmallar per domän
# ---------------------------------------------------------------------------

DOMAIN_PROMPTS = {
    "ufo": (
        "Du är en informationsanalytiker som bevakar UFO/UAP-nyheter åt Arvas International. "
        "Skriv en sammanfattning på 2–3 meningar (ca 8 ord per mening). "
        "Fokus: vad hände, vem sa det, varför är det intressant för UAP-bevakning. "
        "Inga spekulationer. Skriv på engelska om källan är på engelska, annars svenska."
    ),
    "default": (
        "Du är en informationsanalytiker. "
        "Skriv en faktabaserad sammanfattning på 2–3 meningar (ca 8 ord per mening). "
        "Fokus: huvudbudskap, källa, relevans. Inga spekulationer."
    ),
}


def _get_system_prompt(domain: str) -> str:
    return DOMAIN_PROMPTS.get(domain, DOMAIN_PROMPTS["default"])


# ---------------------------------------------------------------------------
# Transkript → text för Claude
# ---------------------------------------------------------------------------

def _transcript_to_text(transcript_path: str, max_chars: int = MAX_TRANSCRIPT_CHARS) -> str:
    """
    Läser transkript-JSON och returnerar ren text (utan tidsstämplar),
    trunkerad till max_chars. Tar mitten av transkriptet om det är för långt —
    intro och outro innehåller ofta minst kärna.
    """
    path = Path(transcript_path)
    if not path.exists():
        raise FileNotFoundError(f"Transkript saknas: {path}")

    segments: list[dict] = json.loads(path.read_text(encoding="utf-8"))
    full_text = " ".join(s["text"] for s in segments if s.get("text"))

    if len(full_text) <= max_chars:
        return full_text

    # Trunkera: ta från ~10% in (hoppa intro-prat) och håll max_chars
    start = max(0, len(full_text) // 10)
    return full_text[start : start + max_chars]


# ---------------------------------------------------------------------------
# Summering
# ---------------------------------------------------------------------------

def summarize_item(conn, item_id: int) -> Optional[str]:
    """
    Sammanfattar ett transkriberat objekt med Claude.
    Returnerar summary-strängen, eller None vid fel.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic saknas — kör: pip install anthropic")

    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY saknas i .env")

    item = conn.execute(
        "SELECT * FROM vigil_items WHERE id = ?", (item_id,)
    ).fetchone()

    if not item:
        logger.error(f"Item {item_id} hittades inte")
        return None

    if not item["transcript_path"]:
        logger.warning(f"Item {item_id} saknar transcript_path")
        return None

    try:
        transcript_text = _transcript_to_text(item["transcript_path"])
    except FileNotFoundError as e:
        logger.error(str(e))
        return None

    system_prompt = _get_system_prompt(item["domain"])
    user_message  = (
        f"Titel: {item['title'] or '—'}\n"
        f"Källa: {item['source_name'] or '—'}\n"
        f"Publicerad: {(item['published_at'] or '—')[:10]}\n\n"
        f"Transkript:\n{transcript_text}"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        summary = response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude API-fel för item {item_id}: {e}")
        return None

    conn.execute(
        "UPDATE vigil_items SET summary = ? WHERE id = ?",
        (summary, item_id),
    )
    conn.commit()

    logger.info(f"Item {item_id} sammanfattad: {summary[:80]}…")
    return summary


# ---------------------------------------------------------------------------
# Batchkörning
# ---------------------------------------------------------------------------

def run_summarizer(conn, domain: Optional[str] = None, max_items: int = 20) -> dict:
    """
    Sammanfattar alla transcribed-objekt som saknar summary.
    Returnerar räknare: {done, failed}.
    """
    query = """
        SELECT id FROM vigil_items
        WHERE state IN ('transcribed', 'indexed', 'notified')
          AND (summary IS NULL OR summary = '')
          {}
        ORDER BY priority_score DESC
        LIMIT ?
    """.format("AND domain = ?" if domain else "")

    params = (domain, max_items) if domain else (max_items,)
    rows = conn.execute(query, params).fetchall()

    counts = {"done": 0, "failed": 0}
    for row in rows:
        result = summarize_item(conn, row["id"])
        if result:
            counts["done"] += 1
        else:
            counts["failed"] += 1

    return counts


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
        description="clio-vigil summarizer — sammanfattar transkript via Claude"
    )
    parser.add_argument("--run", action="store_true",
                        help="Kör batch-summering")
    parser.add_argument("--item", type=int,
                        help="Sammanfatta specifikt item-ID")
    parser.add_argument("--domain", type=str,
                        help="Begränsa till domän")
    parser.add_argument("--max", type=int, default=20,
                        help="Max antal objekt (default: 20)")
    args = parser.parse_args()

    conn = init_db()

    if args.item:
        summary = summarize_item(conn, args.item)
        if summary:
            print(f"\n✓ Summary:\n{summary}")
        else:
            print("✗ Summering misslyckades")

    elif args.run:
        counts = run_summarizer(conn, domain=args.domain, max_items=args.max)
        print(f"\n✓ Summering: {counts['done']} klara, {counts['failed']} misslyckade")

    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    _main()
