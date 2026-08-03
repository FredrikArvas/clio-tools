"""
clio-vigil — summarizer.py
===========================
Sammanfattar transkriberade bevakningsobjekt.

Primär motor: Ollama (lokal, gratis) via LOCAL_MODEL (default: qwen2.5:3b).
  - Kör hela transkriptet i chunk-loopar (14 000 chars/chunk, 2-4 meningar/chunk).
  - Passar qwen2.5:3b:s 4096-token kontextfönster utan trunkering.
  - Konkatenerar alla chunk-summaries till ett komplett dokument.

Fördjupningsanalys: Claude API för objekt med priority_score >= CLAUDE_THRESHOLD.
  - Trunkerar transkript till MAX_TRANSCRIPT_CHARS (Claude hanterar längre kontext).

# ÅTERGÅNG TILL CLAUDE-ONLY
# Sätt CLAUDE_THRESHOLD=0.0 i .env för att skicka ALLT till Claude.
# Eller byt LOCAL_MODEL="" för att inaktivera lokal motor helt.

Flöde:
  1. Hämta objekt med state IN (transcribed, ...) OCH transcript_path IS NOT NULL
  2. Läs in transkript-JSON (segments med tidsstämplar)
  3. priority_score >= CLAUDE_THRESHOLD → Claude API (djupanalys, trunkerat)
     priority_score <  CLAUDE_THRESHOLD → Ollama chunk-loop (full längd)
  4. Spara summary i vigil_items.summary
  5. Sätter state = summarized

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

from orchestrator import init_db, transition

logger = logging.getLogger(__name__)

_here = Path(__file__).parent
# Ladda parent .env först (innehåller ANTHROPIC_API_KEY), sedan vigil-specifik .env med override
load_dotenv(_here.parent / ".env")
load_dotenv(_here / ".env", override=True)

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL        = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Lokal motor — qwen2.5:3b (1.9 GB, ryms i GTX 1050 Ti 4 GB)
# mistral:7b (4.4 GB) överstiger GPU-minnet och kör på CPU — för långsamt
# ÅTERGÅNG: sätt LOCAL_MODEL="" i .env för att inaktivera och alltid använda Claude
LOCAL_MODEL         = os.getenv("LOCAL_MODEL", "qwen2.5:3b")
OLLAMA_HOST         = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Tröskelvärde: objekt med priority_score >= detta skickas till Claude, resten till Ollama
# ÅTERGÅNG: sätt CLAUDE_THRESHOLD=0.0 i .env för att alltid använda Claude
CLAUDE_THRESHOLD    = float(os.getenv("CLAUDE_THRESHOLD", "0.5"))

# Claude-path: trunkera till 20 000 chars (Claude hanterar längre kontext fint)
MAX_TRANSCRIPT_CHARS = 20_000

# Ollama chunk-loop: 14 000 chars per chunk (~3 500 tokens + ~500 tokens prompt/output overhead
# = 4 000 tokens total, inom qwen2.5:3b:s 4096-token fönster)
LOCAL_CHUNK_SIZE = 14_000

# ---------------------------------------------------------------------------
# Promptmallar per domän
# ---------------------------------------------------------------------------

# Promptmallar för Claude (mer naturlig instruktion räcker)
DOMAIN_PROMPTS = {
    "ufo": (
        "Du är en informationsanalytiker som bevakar UFO/UAP-nyheter åt Arvas International. "
        "Skriv en sammanfattning på 4–6 meningar. "
        "Fokus: vad hände, vem sa det, centrala påståenden, nämnd bevisning, "
        "och varför det är intressant för UAP-bevakning. "
        "Inga spekulationer. Skriv på engelska om källan är på engelska, annars svenska."
    ),
    "default": (
        "Du är en informationsanalytiker. "
        "Skriv en faktabaserad sammanfattning på 4–6 meningar. "
        "Fokus: huvudbudskap, centrala detaljer, källa, relevans. Inga spekulationer."
    ),
}

# Promptmallar för lokal Ollama-modell (qwen2.5:3b).
# Kräver hårdare format-styrning — modellen tenderar att svara konversationsmässigt
# om inte output-formatet specificeras explicit i system-prompten.
LOCAL_DOMAIN_PROMPTS = {
    "ufo": (
        "You are a summarization tool for UAP/UFO news monitoring. "
        "OUTPUT FORMAT: exactly 4-6 sentences of factual summary, nothing else. "
        "DO NOT respond to the text. DO NOT give advice. DO NOT add commentary. "
        "Focus on: what happened, who said it, key claims, evidence mentioned, "
        "and why it is relevant to UAP research. "
        "Preserve proper nouns exactly as they appear in the source (place names, person names). "
        "No speculation. Match the language of the source (English or Swedish)."
    ),
    "default": (
        "You are a summarization tool. "
        "OUTPUT FORMAT: exactly 4-6 sentences of factual summary, nothing else. "
        "DO NOT respond to the text. DO NOT give advice. DO NOT add commentary. "
        "Focus on: main message, key details, source, relevance. No speculation."
    ),
}


def _get_system_prompt(domain: str, local: bool = False) -> str:
    prompts = LOCAL_DOMAIN_PROMPTS if local else DOMAIN_PROMPTS
    return prompts.get(domain, prompts["default"])


# ---------------------------------------------------------------------------
# Transkript → text
# ---------------------------------------------------------------------------

def _transcript_to_text(transcript_path: str) -> str:
    """Returnerar hela transkripttexten utan trunkering. Trunkering sker i motorpath."""
    path = Path(transcript_path)
    if not path.exists():
        raise FileNotFoundError(f"Transkript saknas: {path}")

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"Tom transkriptfil (avbruten körning?): {path}")

    try:
        segments: list[dict] = json.loads(raw)
        return " ".join(s["text"] for s in segments if s.get("text"))
    except (json.JSONDecodeError, TypeError):
        return raw


# ---------------------------------------------------------------------------
# Summering via Ollama — chunk-loop (lokal, gratis, full transkriptlängd)
# ---------------------------------------------------------------------------

def _ollama_call(system_prompt: str, user_message: str, item_id: int) -> Optional[str]:
    """Enskilt Ollama-anrop. Returnerar svarstext eller None vid fel."""
    try:
        import httpx
    except ImportError:
        logger.error("httpx saknas — kör: pip install httpx")
        return None

    payload = {
        "model": LOCAL_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {"num_predict": 500},
    }
    try:
        response = httpx.post(
            f"{OLLAMA_HOST}/api/chat",
            json=payload,
            timeout=300.0,
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Ollama-fel (item {item_id}): {e}")
        return None


def _summarize_with_ollama(item: dict, full_text: str) -> Optional[str]:
    """
    Primär motor: kör hela transkriptet genom en chunk-loop.
    Varje chunk (LOCAL_CHUNK_SIZE chars) ger 2-4 meningar.
    Alla chunk-summaries konkateneras till ett komplett dokument.
    """
    system_prompt = _get_system_prompt(item["domain"], local=True)
    title   = item["title"] or "—"
    source  = item["source_name"] or "—"
    date    = (item["published_at"] or "—")[:10]

    chunks = [
        full_text[i : i + LOCAL_CHUNK_SIZE]
        for i in range(0, max(len(full_text), 1), LOCAL_CHUNK_SIZE)
    ]
    total  = len(chunks)
    logger.info(f"Item {item['id']}: {len(full_text):,} tecken → {total} chunk(s)")

    part_summaries: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        part_label = f"part {idx}/{total}" if total > 1 else ""
        user_message = (
            f"Summarize the following transcript excerpt in 2-4 sentences. {part_label}\n\n"
            f"<title>{title}</title>\n"
            f"<source>{source}</source>\n"
            f"<date>{date}</date>\n"
            f"<transcript>\n{chunk}\n</transcript>\n\n"
            f"Summary (2-4 sentences only):"
        )
        part = _ollama_call(system_prompt, user_message, item["id"])
        if part:
            part_summaries.append(part)
            logger.info(f"Item {item['id']} chunk {idx}/{total}: {part[:60]}…")
        else:
            logger.warning(f"Item {item['id']} chunk {idx}/{total} misslyckades — hoppar över")

    if not part_summaries:
        return None
    return " ".join(part_summaries)


# ---------------------------------------------------------------------------
# Summering via Claude API (fördjupningsanalys för hög prioritet)
# ---------------------------------------------------------------------------

def _summarize_with_claude(item: dict, transcript_text: str) -> Optional[str]:
    """
    Fördjupningsanalys: Claude API.
    Används för objekt med priority_score >= CLAUDE_THRESHOLD.

    # ÅTERGÅNG TILL CLAUDE-ONLY: anropa denna funktion för alla items.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic saknas — kör: pip install anthropic")

    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY saknas i .env")

    system_prompt = _get_system_prompt(item["domain"])
    # Trunkera för Claude: ta från 10% in för att hoppa intro-prat
    text = transcript_text
    if len(text) > MAX_TRANSCRIPT_CHARS:
        start = max(0, len(text) // 10)
        text = text[start : start + MAX_TRANSCRIPT_CHARS]
    user_message = (
        f"Titel: {item['title'] or '—'}\n"
        f"Källa: {item['source_name'] or '—'}\n"
        f"Publicerad: {(item['published_at'] or '—')[:10]}\n\n"
        f"Transkript:\n{text}"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Summering — router
# ---------------------------------------------------------------------------

def summarize_item(conn, item_id: int) -> Optional[str]:
    """
    Sammanfattar ett transkriberat objekt.
    Väljer motor baserat på priority_score och konfiguration.
    """
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

    priority = item["priority_score"] or 0.0
    use_claude = (priority >= CLAUDE_THRESHOLD) or not LOCAL_MODEL

    if use_claude:
        engine = f"Claude ({CLAUDE_MODEL})"
        try:
            summary = _summarize_with_claude(item, transcript_text)
        except Exception as e:
            logger.error(f"Claude API-fel för item {item_id}: {e}")
            # Fallback till Ollama om Claude misslyckas
            logger.info(f"Item {item_id}: faller tillbaka på Ollama efter Claude-fel")
            summary = _summarize_with_ollama(item, transcript_text)
    else:
        engine = f"Ollama ({LOCAL_MODEL})"
        summary = _summarize_with_ollama(item, transcript_text)
        if summary is None:
            # Fallback till Claude om Ollama misslyckas
            logger.warning(f"Item {item_id}: Ollama misslyckades, faller tillbaka på Claude")
            try:
                summary = _summarize_with_claude(item, transcript_text)
                engine = f"Claude-fallback ({CLAUDE_MODEL})"
            except Exception as e:
                logger.error(f"Även Claude misslyckades för item {item_id}: {e}")
                return None

    if not summary:
        return None

    conn.execute(
        "UPDATE vigil_items SET summary = ? WHERE id = ?",
        (summary, item_id),
    )
    conn.commit()
    transition(conn, item_id, "summarized")

    logger.info(f"Item {item_id} [{engine}] (prio={priority:.2f}): {summary[:80]}…")
    return summary


# ---------------------------------------------------------------------------
# Batchkörning
# ---------------------------------------------------------------------------

def run_summarizer(conn, domain: Optional[str] = None, max_items: int = 20, odoo_env=None) -> dict:
    """
    Sammanfattar objekt som har transkript men saknar summary.
    Obs: filtrerar aktivt bort items utan transcript_path — de kan aldrig summeras
    via transkript-flödet och ska inte ta upp slots i kön.
    """
    query = """
        SELECT id FROM vigil_items
        WHERE state IN ('transcribed', 'captioned', 'summarized', 'indexed', 'notified')
          AND (summary IS NULL OR summary = '')
          AND transcript_path IS NOT NULL AND transcript_path != ''
          {}
        ORDER BY priority_score DESC
        LIMIT ?
    """.format("AND domain = ?" if domain else "")

    params = (domain, max_items) if domain else (max_items,)
    rows = conn.execute(query, params).fetchall()

    counts = {"done": 0, "failed": 0, "claude": 0, "ollama": 0}
    for row in rows:
        try:
            result = summarize_item(conn, row["id"])
            if result:
                counts["done"] += 1
                # Flytta till summarized om item kom från transcribed/captioned
                item_state = conn.execute(
                    "SELECT state FROM vigil_items WHERE id=?", (row["id"],)
                ).fetchone()
                if item_state and item_state["state"] in ("transcribed", "captioned"):
                    transition(conn, row["id"], "summarized")
                if odoo_env is not None:
                    try:
                        from odoo_writer import sync_single_item
                        sync_single_item(odoo_env, conn, row["id"])
                    except Exception as _e:
                        logger.warning("Odoo-sync misslyckades for item %d: %s", row["id"], _e)
            else:
                counts["failed"] += 1
        except (ValueError, FileNotFoundError) as e:
            logger.warning(f"Hoppar över item {row['id']}: {e}")
            transition(conn, row["id"], "discovered")
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
        description="clio-vigil summarizer — primär: Ollama, fördjupning: Claude"
    )
    parser.add_argument("--run", action="store_true", help="Kör batch-summering")
    parser.add_argument("--item", type=int, help="Sammanfatta specifikt item-ID")
    parser.add_argument("--domain", type=str, help="Begränsa till domän")
    parser.add_argument("--max", type=int, default=20, help="Max antal objekt (default: 20)")
    args = parser.parse_args()

    logger.info(
        f"Summarizer: lokal={LOCAL_MODEL or 'av'} chunk={LOCAL_CHUNK_SIZE}, "
        f"claude-tröskel={CLAUDE_THRESHOLD} max={MAX_TRANSCRIPT_CHARS}"
    )

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
