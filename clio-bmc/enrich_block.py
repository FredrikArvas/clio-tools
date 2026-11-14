"""
enrich_block.py -- Berikar ett BMC-block med Claude-reasoning och valfri URL-fetch.

Berikningsladen:
  reasoning (default) -- Claude resonerar pa block-texten utan extern data
  url-fetch (tillval) -- Tillfogad HTML fran --url skickas med som kontext
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / '.env', override=True)
load_dotenv(Path(__file__).parent / '.env', override=False)

import anthropic

from session import BLOCK_DISPLAY, BLOCK_NAMES, save, set_block_enriched

MODEL      = 'claude-haiku-4-5-20251001'
MAX_TOKENS = 2048
MAX_URL_CHARS = 60_000

_BLOCK_PROMPTS = {
    'kundsegment': """\
Du analyserar ett BMC-block om Kundsegment.

Berikning:
1. Segmentprecision -- ar segmentet tillrackligt specifikt eller for brett?
2. Persona-djup -- vad vet vi om kunden som person/organisation?
3. Blinda flackar -- vilka antaganden bor utmanas?

Om URL-innehall medfoljt: identifiera hur liknande bolag segmenterar sina kunder.

Returnera strukturerad analys (max 400 ord) med rubriker.""",

    'vardeerbjudande': """\
Du analyserar ett BMC-block om Vardeerbjudande.

Berikning:
1. Kundnytta vs feature-lista -- ar VP formulerat som kundnytta?
2. Alternativ -- vad anvander kunden om de inte valjer detta?
3. Spanning mot kundsegment -- ar VP ratt for det segmentet?

Om URL-innehall medfoljt: extrahera hur konkurrenter positionerar sig.

Returnera strukturerad analys (max 400 ord) med rubriker.""",

    'kanaler': """\
Du analyserar ett BMC-block om Kanaler.

Berikning:
1. Kanalval vs branschnorm -- ar kanalen rimlig for branschen?
2. Realism -- ar kanalen onsketankande (t.ex. viral spridning)?
3. Spanning mot kundrelationer -- kan kanalen bara den relationstypen?

Returnera strukturerad analys (max 400 ord) med rubriker.""",

    'kundrelationer': """\
Du analyserar ett BMC-block om Kundrelationer.

Berikning:
1. Skalbarhet -- kan relationsmodellen vaxa utan proportionell kostnad?
2. Kongruens med kanal -- stammer kanal och relationsmodell overens?
3. Livscykel -- vad hander med kunden efter forsta kop?

Returnera strukturerad analys (max 400 ord) med rubriker.""",

    'intaktsstromar': """\
Du analyserar ett BMC-block om Intaktsstromar.

Berikning:
1. Tillvaxtstod -- stodjer intaktsmodellen tillvaxt eller ar den engangsvisa?
2. Spanning mot VP -- ar erbjudandet vart att betala for?
3. Branschnorm -- om mojligt, jamfor med liknande affarsmodeller.

Returnera strukturerad analys (max 400 ord) med rubriker.""",

    'nyckelresurser': """\
Du analyserar ett BMC-block om Nyckelresurser.

Berikning:
1. Kritiskt vs nice-to-have -- vad ar faktiskt nyckelresurs?
2. Aga vs hyra -- maste det agas eller kan det outsourcas?
3. Spanning mot kostnadsstruktur -- rad vi oss med det vi planerat?

Returnera strukturerad analys (max 400 ord) med rubriker.""",

    'nyckelaktiviteter': """\
Du analyserar ett BMC-block om Nyckelaktiviteter.

Berikning:
1. Strategiska vs operativa -- sarskilt de tva typerna.
2. Outsourcing-potential -- vad kan delegeras utan att skada VP:n?
3. Koppling till nyckelresurser -- kravs dessa resurser for dessa aktiviteter?

Returnera strukturerad analys (max 400 ord) med rubriker.""",

    'nyckelpartners': """\
Du analyserar ett BMC-block om Nyckelpartners.

Berikning:
1. Existentiella vs taktiska -- vilka partners ar kritiska?
2. Koncentrationsrisk -- vad hander om en partner forsvinner?
3. Strategisk vs inkopsrelation -- ar det verkligen partnerskap eller leverantor?

Returnera strukturerad analys (max 400 ord) med rubriker.""",

    'kostnadsstruktur': """\
Du analyserar ett BMC-block om Kostnadsstruktur.

Berikning:
1. Tunga kostnadsposter och deras koppling till nyckelresurser/aktiviteter.
2. Break-even -- finns information for att bedoma det?
3. Spanning mot intaktsstromar -- ar modellen ekonomiskt hallbar?

Returnera strukturerad analys (max 400 ord) med rubriker.""",
}


def enrich(session: dict, block_name: str, url_html: str = None,
           base_dir=None) -> str:
    """
    Berikar ett block med Claude-reasoning.

    Args:
        session:    Aktiv session-dict.
        block_name: Namn pa blocket, t.ex. 'kundsegment'.
        url_html:   Rensat HTML fran valfri URL (None = rent reasoning-lade).
        base_dir:   Overrida sessions-katalog (anvands i tester).

    Returns:
        Berikad text. Tom strang om coach-text saknas.
    """
    if block_name not in BLOCK_NAMES:
        raise ValueError(f'Okant block: {block_name}. Giltiga: {BLOCK_NAMES}')

    block = session['blocks'][block_name]
    coach_text = (block.get('coach_text') or '').strip()
    if not coach_text:
        print(f'  Hoppar {block_name} (ingen coach-text).')
        return ''

    display = BLOCK_DISPLAY[block_name]
    parts = [
        f'Block: {display}\n\n',
        f'Coach-session text:\n{coach_text}\n\n',
        _BLOCK_PROMPTS[block_name],
    ]
    if url_html:
        parts.append(f'\nURL-innehall (rensat HTML):\n{url_html[:MAX_URL_CHARS]}\n')

    client = anthropic.Anthropic()
    print(f'  Skickar {block_name} till Claude ({MODEL}) ...')

    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{'role': 'user', 'content': ''.join(parts)}],
    )

    enriched = msg.content[0].text.strip()
    urls = [url_html[:200]] if url_html else []
    set_block_enriched(session, block_name, enriched, urls)
    save(session, base_dir)
    print(f'  Berikat: {len(enriched)} tecken')
    return enriched


def enrich_all(session: dict, base_dir=None) -> int:
    """Berikar alla block som har coach-text. Returnerar antal berikade."""
    count = 0
    for block_name in BLOCK_NAMES:
        if (session['blocks'][block_name].get('coach_text') or '').strip():
            enrich(session, block_name, base_dir=base_dir)
            count += 1
        else:
            print(f'  Hoppar {block_name} (ingen coach-text).')
    return count
