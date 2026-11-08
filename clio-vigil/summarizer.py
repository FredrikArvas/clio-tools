"""
clio-vigil — summarizer.py
===========================
Sammanfattar transkriberade bevakningsobjekt.

Primär motor: Ollama (lokal, gratis) via LOCAL_MODEL (default: qwen2.5:3b).
  - Kör hela transkriptet i chunk-loopar (14 000 chars/chunk, 2-4 meningar/chunk).
  - Passar qwen2.5:3b:s 4096-token kontextfönster utan trunkering.
  - Konkatenerar alla chunk-summaries till ett komplett dokument.

Fördjupningsanalys: Claude Sonnet för objekt med priority_score >= CLAUDE_THRESHOLD.
  - Körs på prenumerationen via `claude -p` (clio-research/claude_runner.py),
    eller Anthropic API med VIGIL_CLAUDE_BACKEND=api.
  - Trunkerar transkript till MAX_TRANSCRIPT_CHARS (Claude hanterar längre kontext).
  - Misslyckas Claude (fel, kvotgräns) tar Ollama över.

# ÅTERGÅNG TILL CLAUDE-ONLY
# Sätt CLAUDE_THRESHOLD=0.0 i .env för att skicka ALLT till Claude.
# Eller byt LOCAL_MODEL="" för att inaktivera lokal motor helt.

Flöde:
  1. Hämta objekt utan summary som har transcript_path, eller (textposter)
     description ≥ MIN_TEXT_CHARS
  2. Läs in transkript-JSON (segments med tidsstämplar), eller title + description
  3. priority_score >= CLAUDE_THRESHOLD → Claude API (djupanalys, trunkerat)
     priority_score <  CLAUDE_THRESHOLD → Ollama chunk-loop (full längd)
  4. Spara summary i vigil_items.summary
  5. Sätter state = summarized (bara från transcribed/captioned; indexed ligger kvar)

Körning:
  python summarizer.py --run [--domain ufo] [--max 20]
  python summarizer.py --item 42
"""

import json
import logging
import os
import re
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

MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL        = os.getenv("CLAUDE_MODEL", MODEL_SONNET)

# Claude-steget körs på prenumerationen via `claude -p` (Claude Code inloggat på
# servern). VIGIL_CLAUDE_BACKEND=api går tillbaka till Anthropic API (per token).
BACKEND_SUBSCRIPTION = "subscription"
BACKEND_API          = "api"
CLAUDE_BACKEND       = os.getenv("VIGIL_CLAUDE_BACKEND", BACKEND_SUBSCRIPTION)
# Körkatalog utanför git-repot, så att repots CLAUDE.md inte laddas i prompten
CLAUDE_WORKDIR       = Path(os.getenv("VIGIL_CLAUDE_WORKDIR",
                                      str(Path.home() / ".cache" / "clio-vigil-claude")))
CLAUDE_TIMEOUT_SECONDS = 300
OUTPUT_ONLY_INSTRUCTION = (
    "Svara ENBART med sammanfattningstexten. Inga tokenestimat, inga skämt, "
    "ingen inledning eller avslutning."
)
CLI_FOOTER_PATTERN = re.compile(r"^\s*(📊|🎪|---\s*$)")

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

# Textposter (RSS/webb utan transkript) sammanfattas från title + description
# om description är minst så här lång. Kortare (t.ex. Google News "rubrik - källa")
# ger inget att sammanfatta — digesten visar då description direkt.
MIN_TEXT_CHARS = 400

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


def _description_text(item) -> str:
    """Description som ren text (HTML-entiteter avkodade, blanktecken hopslagna)."""
    import html
    return " ".join(html.unescape(item["description"] or "").split())


def _item_source_text(item) -> Optional[str]:
    """
    Text att sammanfatta: transkript om det finns, annars title + description
    för textposter med tillräckligt lång description. None om inget finns.
    Kastar FileNotFoundError/ValueError om transkriptfilen saknas eller är tom.
    """
    if item["transcript_path"]:
        return _transcript_to_text(item["transcript_path"])
    # Samma längdmått som SQL-urvalet i run_summarizer (rå längd), så att en
    # vald post aldrig avvisas här och väljs om och om igen.
    if len(item["description"] or "") < MIN_TEXT_CHARS:
        return None
    description = _description_text(item)
    return f"{item['title'] or ''}\n\n{description}".strip()


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
# Summering via Claude (fördjupningsanalys för hög prioritet)
# ---------------------------------------------------------------------------

def _claude_user_message(item: dict, transcript_text: str) -> str:
    """Promptens användardel. Trunkerar från 10 % in för att hoppa intro-prat."""
    text = transcript_text
    if len(text) > MAX_TRANSCRIPT_CHARS:
        start = max(0, len(text) // 10)
        text = text[start : start + MAX_TRANSCRIPT_CHARS]
    return (
        f"Titel: {item['title'] or '—'}\n"
        f"Källa: {item['source_name'] or '—'}\n"
        f"Publicerad: {(item['published_at'] or '—')[:10]}\n\n"
        f"Text:\n{text}"
    )


def _summarize_with_claude(item: dict, transcript_text: str) -> Optional[str]:
    """
    Fördjupningsanalys för objekt med priority_score >= CLAUDE_THRESHOLD.
    Kör via prenumerationen (`claude -p`) eller API:t beroende på CLAUDE_BACKEND.
    Kastar vid fel, så att summarize_item faller tillbaka på Ollama.
    """
    system_prompt = _get_system_prompt(item["domain"])
    user_message = _claude_user_message(item, transcript_text)
    if CLAUDE_BACKEND == BACKEND_SUBSCRIPTION:
        return _call_claude_subscription(system_prompt, user_message)
    return _call_claude_api(system_prompt, user_message)


def _call_claude_api(system_prompt: str, user_message: str) -> str:
    """Claude via Anthropic API (debiteras per token)."""
    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic saknas — kör: pip install anthropic")
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY saknas i .env")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text.strip()


_claude_runner = None
_is_subscription_limited = False


def _load_claude_runner():
    """Delad `claude -p`-körare från clio-research (tar bort API-nyckeln ur miljön)."""
    global _claude_runner
    if _claude_runner is None:
        import importlib.util
        path = _here.parent / "clio-research" / "claude_runner.py"
        spec = importlib.util.spec_from_file_location("claude_runner", path)
        module = importlib.util.module_from_spec(spec)
        # Dataclasses i modulen slår upp sys.modules[__module__] — registrera först.
        sys.modules["claude_runner"] = module
        spec.loader.exec_module(module)
        _claude_runner = module
    return _claude_runner


def _strip_cli_extras(text: str) -> str:
    """
    Tar bort det serverns globala ~/.claude/CLAUDE.md lägger till (tokenfot,
    skämt efter '---'). Det laddas trots --setting-sources project.
    """
    lines = text.strip().splitlines()
    for idx, line in enumerate(lines):
        if CLI_FOOTER_PATTERN.match(line):
            lines = lines[:idx]
            break
    return "\n".join(lines).strip()


def _call_claude_subscription(system_prompt: str, user_message: str) -> str:
    """Claude via `claude -p` på prenumerationen. Slutar försöka resten av körningen vid kvotgräns."""
    global _is_subscription_limited
    if _is_subscription_limited:
        raise RuntimeError("Prenumerationens kvot nådd tidigare i körningen")

    runner = _load_claude_runner()
    CLAUDE_WORKDIR.mkdir(parents=True, exist_ok=True)
    result = runner.run_claude(
        "analyst", user_message, CLAUDE_MODEL, CLAUDE_WORKDIR,
        system_prompt=f"{system_prompt} {OUTPUT_ONLY_INSTRUCTION}",
        max_turns=1, timeout_s=CLAUDE_TIMEOUT_SECONDS,
    )
    if result.status == runner.STATUS_LIMIT:
        _is_subscription_limited = True
        logger.warning("claude -p: kvotgräns — resten av körningen går till Ollama")
    if not result.is_ok:
        raise RuntimeError(f"claude -p {result.status}: {result.message}")
    summary = _strip_cli_extras(result.text)
    if not summary:
        raise RuntimeError("claude -p gav tomt svar")
    return summary


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

    try:
        transcript_text = _item_source_text(item)
    except FileNotFoundError as e:
        logger.error(str(e))
        return None
    if transcript_text is None:
        logger.warning(
            f"Item {item_id} saknar transkript och description ≥ {MIN_TEXT_CHARS} tecken"
        )
        return None

    priority = item["priority_score"] or 0.0
    use_claude = (priority >= CLAUDE_THRESHOLD) or not LOCAL_MODEL

    if use_claude:
        engine = f"Claude ({CLAUDE_MODEL})"
        try:
            summary = _summarize_with_claude(item, transcript_text)
        except Exception as e:
            logger.error(f"Claude-fel för item {item_id}: {e}")
            # Fallback till Ollama om Claude misslyckas
            logger.info(f"Item {item_id}: faller tillbaka på Ollama efter Claude-fel")
            engine = f"Ollama-fallback ({LOCAL_MODEL})"
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
    # Bara poster som väntar på summering flyttas fram. En redan indexerad post
    # ska ligga kvar som indexed, annars missar digesten den.
    if item["state"] in ("transcribed", "captioned"):
        transition(conn, item_id, "summarized")

    logger.info(f"Item {item_id} [{engine}] (prio={priority:.2f}): {summary[:80]}…")
    return summary


# ---------------------------------------------------------------------------
# Batchkörning
# ---------------------------------------------------------------------------

def run_summarizer(conn, domain: Optional[str] = None, max_items: int = 20, odoo_env=None) -> dict:
    """
    Sammanfattar objekt som saknar summary och har något att sammanfatta:
    transkript, eller (textposter) en description på minst MIN_TEXT_CHARS tecken.
    Poster utan något av dem väljs aldrig, så de tar inte slots i kön.
    """
    query = """
        SELECT id FROM vigil_items
        WHERE state IN ('transcribed', 'captioned', 'summarized', 'indexed', 'notified')
          AND (summary IS NULL OR summary = '')
          AND ((transcript_path IS NOT NULL AND transcript_path != '')
               OR length(coalesce(description, '')) >= ?)
          {}
        ORDER BY priority_score DESC
        LIMIT ?
    """.format("AND domain = ?" if domain else "")

    params = ((MIN_TEXT_CHARS, domain, max_items) if domain
              else (MIN_TEXT_CHARS, max_items))
    rows = conn.execute(query, params).fetchall()

    counts = {"done": 0, "failed": 0, "claude": 0, "ollama": 0}
    for row in rows:
        try:
            result = summarize_item(conn, row["id"])
            if result:
                counts["done"] += 1
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
