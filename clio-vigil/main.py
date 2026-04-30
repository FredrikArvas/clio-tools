"""
clio-vigil — main.py
=====================
Huvudingång för clio-vigil bevakningsagent.

Körlägen:
  python main.py --run          Kör full pipeline (collect → filter → queue)
  python main.py --stats        Visa tillståndsstatistik
  python main.py --list-queued  Lista objekt i transkriptionskö
  python main.py --domain ufo   Begränsa till en domän

Schemaläggning via systemd timer (WSL2):
  Se install/vigil.timer och vigil.service

Designbeslut (ADD v0.2, 2026-04-18):
  - YAML-konfiguration för MVP (migreras till Odoo i Release 1.5)
  - Pipeline: collect → filter → [transcribe i separat process]
  - Transkription körs separat (GPU-intensiv, preemptiv)
"""

import argparse
import logging
import sys
from pathlib import Path

# Windows: säkerställ UTF-8 output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Windows: tvinga IPv4 DNS (Python 3.14 misslyckas med IPv6 link-local DNS-server)
if sys.platform == "win32":
    import socket as _socket
    _orig_getaddrinfo = _socket.getaddrinfo
    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if family == 0:
            family = _socket.AF_INET
        return _orig_getaddrinfo(host, port, family, type, proto, flags)
    _socket.getaddrinfo = _ipv4_getaddrinfo

import yaml

from orchestrator import init_db, stats, domain_stats, upsert_item, transition
from filter import run_filter
from collectors.rss_collector import collect_rss
from collectors.youtube_collector import collect_youtube

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(stream=open(sys.stdout.fileno(), mode="w",
                                                encoding="utf-8", closefd=False))],
)
logger = logging.getLogger("clio-vigil")

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

CONFIG_DIR = Path(__file__).parent / "config"


def load_domain_config(domain_id: str) -> dict:
    """Laddar YAML-konfiguration för en domän."""
    path = CONFIG_DIR / f"{domain_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Domänkonfiguration saknas: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_all_domains() -> list[str]:
    """Returnerar alla konfigurerade domäner."""
    return [p.stem for p in CONFIG_DIR.glob("*.yaml")]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def import_url(conn, url: str, domain: str) -> None:
    """
    Manuell import av en webb-sida eller PDF-URL.
    Extraherar text direkt, hoppar över transkriptionskön,
    lägger in som 'transcribed' redo för summera + indexera.
    """
    from text_extractor import extract
    from datetime import datetime, timezone

    print(f"\n📥 Importerar: {url}")
    print(f"   Domän: {domain}")

    # Temporärt ID för filnamn — ersätts med riktigt ID efter insert
    tmp_id = int(datetime.now(timezone.utc).timestamp())
    result = extract(url, item_id=tmp_id, source_name=domain, date="")

    if not result:
        print("✗ Extraktion misslyckades.")
        return

    source_type = result["source_type"]
    title       = result["title"] or url[:80]
    word_count  = result["word_count"]

    print(f"   Typ: {source_type}  |  {word_count:,} ord  |  {title[:60]}")

    # Upsert i vigil_items (hoppar om URL redan finns)
    item_id = upsert_item(
        conn,
        url=url,
        domain=domain,
        source_type=source_type,
        source_name=f"import-{source_type}",
        source_maturity="tidig",
        source_weight=1.0,
        title=title,
        description=title,
        published_at=datetime.now(timezone.utc).isoformat(),
        duration_seconds=None,
        raw_metadata="{}",
    )

    if not item_id:
        print("⚠ URL finns redan i databasen — hoppar över.")
        return

    # Döp om filen med riktigt item_id
    from pathlib import Path
    old_path = Path(result["transcript_path"])
    new_name = old_path.name.replace(str(tmp_id), str(item_id))
    new_path = old_path.parent / new_name
    if old_path != new_path:
        old_path.rename(new_path)
        result["transcript_path"] = str(new_path)

    # Sätt state direkt till transcribed (text redan extraherad)
    conn.execute(
        "UPDATE vigil_items SET state='transcribed', transcript_path=? WHERE id=?",
        (result["transcript_path"], item_id)
    )
    conn.commit()

    print(f"✓ Importerad som item {item_id} → redo för summera + indexera")
    print(f"  Kör '3. summera' och '4. indexera' för att processa.")


def pick_source(conn) -> None:
    """
    Interaktiv källväljare: visa alla konfigurerade källor,
    låt användaren välja vilka som ska hämtas in och filtreras.
    """
    # Samla alla källor från alla domäner
    all_sources = []
    for domain_id in get_all_domains():
        try:
            config = load_domain_config(domain_id)
        except Exception:
            continue
        for src in config.get("sources", {}).get("rss", []):
            all_sources.append({
                "domain": domain_id,
                "type": "rss",
                "name": src.get("name", src["url"]),
                "url": src["url"],
                "config": config,
                "src": src,
            })
        for src in config.get("sources", {}).get("youtube", []):
            all_sources.append({
                "domain": domain_id,
                "type": "youtube",
                "name": src.get("name", src.get("channel_id", "?")),
                "url": src.get("channel_id", ""),
                "config": config,
                "src": src,
            })

    if not all_sources:
        print("Inga källor konfigurerade.")
        return

    print(f"\n📡 Välj källa att hämta in ({len(all_sources)} konfigurerade)")
    print("─" * 72)
    for i, s in enumerate(all_sources, 1):
        icon = "🎙" if s["type"] == "rss" else "▶"
        print(f"  {i:>3}. {icon} [{s['domain']}] {s['name']}")
    print("─" * 72)
    print("  Ange nummer (t.ex. 1,3,5 eller 2-6 eller 'alla') — Enter = avbryt")

    raw = input("  Val: ").strip().lower()
    if not raw:
        print("  Avbröts.")
        return

    selected_indices = set()
    if raw == "alla":
        selected_indices = set(range(len(all_sources)))
    else:
        for part in raw.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    selected_indices.update(range(int(a) - 1, int(b)))
                except ValueError:
                    pass
            else:
                try:
                    selected_indices.add(int(part) - 1)
                except ValueError:
                    pass

    selected = [all_sources[i] for i in sorted(selected_indices) if 0 <= i < len(all_sources)]
    if not selected:
        print("  Inga giltiga val.")
        return

    # Gruppera valda källor per domän och bygg filtrerade configs
    from collections import defaultdict
    by_domain = defaultdict(lambda: {"rss": [], "youtube": []})
    for s in selected:
        by_domain[s["domain"]][s["type"]].append(s["src"])

    total_new = 0
    total_queued = 0
    for domain_id, sources in by_domain.items():
        config = load_domain_config(domain_id)
        # Bygg filtrerad config med bara valda källor
        filtered_config = {**config, "sources": sources}

        print(f"\n  Hämtar [{domain_id}]...")
        rss_counts = collect_rss(conn, filtered_config)
        yt_counts  = collect_youtube(conn, filtered_config)
        new = rss_counts["discovered"] + yt_counts["discovered"]
        total_new += new
        print(f"  → {new} nya objekt")

        # Kör filter på nya discovered
        filter_counts = run_filter(conn, config)
        total_queued += filter_counts["filtered_in"]
        print(f"  → {filter_counts['filtered_in']} köade, {filter_counts['filtered_out']} filtrerade bort")

    print(f"\n  ✓ Totalt: {total_new} nya objekt, {total_queued} i kö")


def run_pipeline(conn, domain_id: str) -> None:
    """Kör collect → filter → queue för en domän."""
    logger.info(f"═══ Pipeline start: [{domain_id}] ═══")
    config = load_domain_config(domain_id)

    # Steg 1: Insamling
    rss_counts = collect_rss(conn, config)
    yt_counts = collect_youtube(conn, config)

    total_discovered = rss_counts["discovered"] + yt_counts["discovered"]
    logger.info(f"Insamling: {total_discovered} nya objekt")

    # Steg 2: Relevansfilter
    filter_counts = run_filter(conn, config)
    logger.info(
        f"Filter: {filter_counts['filtered_in']} köade, "
        f"{filter_counts['filtered_out']} filtrerade bort"
    )

    logger.info(f"═══ Pipeline klar: [{domain_id}] ═══")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_stats(conn, domain: str = None) -> None:
    """Skriver ut tillståndsstatistik."""
    if domain:
        d_stats = domain_stats(conn)
        if domain not in d_stats:
            print(f"Ingen data för domän: {domain}")
            return
        print(f"\n📊 Statistik — {domain}")
        for state, count in sorted(d_stats[domain].items()):
            print(f"  {state:<20} {count}")
    else:
        all_stats = stats(conn)
        d_stats = domain_stats(conn)
        print("\n📊 Clio-vigil — översikt")
        print("─" * 35)
        for state, count in sorted(all_stats.items()):
            print(f"  {state:<20} {count}")
        print("\n📁 Per domän:")
        for dom, states in sorted(d_stats.items()):
            total = sum(states.values())
            queued = states.get("queued", 0)
            indexed = states.get("indexed", 0)
            print(f"  {dom:<15} {total} objekt ({queued} i kö, {indexed} indexerade)")


def print_queued(conn, domain: str = None) -> None:
    """Listar objekt i transkriptionskö."""
    query = """
        SELECT v.id, v.domain, v.title, v.source_name,
               v.priority_score, v.duration_seconds, v.source_maturity
        FROM vigil_items v
        WHERE v.state = 'queued'
        {}
        ORDER BY v.priority_score DESC
        LIMIT 20
    """.format("AND v.domain = ?" if domain else "")

    params = (domain,) if domain else ()
    rows = conn.execute(query, params).fetchall()

    if not rows:
        print("Ingen i kö.")
        return

    print(f"\n⏳ Transkriptionskö ({len(rows)} objekt):")
    print("─" * 70)
    for row in rows:
        dur = f"{row['duration_seconds']//60}min" if row['duration_seconds'] else "okänd"
        print(
            f"  [{row['domain']}] prio={row['priority_score']:.3f} "
            f"| {dur} | {row['source_maturity']} "
            f"| {row['title'][:45] if row['title'] else '—'}"
        )


def pick_items(conn, domain: str = None) -> None:
    """
    Interaktiv väljare: visa köade objekt och låt användaren
    boosta valda till toppen av kön (priority_score = 999).
    """
    query = """
        SELECT v.id, v.domain, v.title, v.source_name,
               v.priority_score, v.duration_seconds, v.source_maturity,
               v.published_at
        FROM vigil_items v
        WHERE v.state IN ('queued', 'filtered_in')
        {}
        ORDER BY v.priority_score DESC
    """.format("AND v.domain = ?" if domain else "")

    params = (domain,) if domain else ()
    rows = conn.execute(query, params).fetchall()

    if not rows:
        print("Inga objekt i kö.")
        return

    print(f"\n📋 Välj objekt att prioritera ({len(rows)} i kö)")
    print("─" * 72)
    for i, row in enumerate(rows, 1):
        dur = f"{row['duration_seconds']//60}min" if row['duration_seconds'] else "?min"
        date = (row['published_at'] or "")[:10]
        title = (row['title'] or "—")[:42]
        print(f"  {i:>3}. [{row['domain']}] {title:<42} {dur:>6}  {date}  {row['source_name'][:20]}")

    print("─" * 72)
    print("  Ange nummer (t.ex. 1,3,5 eller 1-5 eller 'alla') — Enter = avbryt")

    raw = input("  Val: ").strip().lower()
    if not raw:
        print("  Avbröts.")
        return

    selected_indices = set()
    if raw == "alla":
        selected_indices = set(range(len(rows)))
    else:
        for part in raw.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    selected_indices.update(range(int(a) - 1, int(b)))
                except ValueError:
                    pass
            else:
                try:
                    selected_indices.add(int(part) - 1)
                except ValueError:
                    pass

    selected = [rows[i] for i in sorted(selected_indices) if 0 <= i < len(rows)]
    if not selected:
        print("  Inga giltiga val.")
        return

    # Boosta valda till toppen (priority_score 999) och sätt state = queued
    for row in selected:
        conn.execute(
            "UPDATE vigil_items SET priority_score = 999, state = 'queued' WHERE id = ?",
            (row["id"],)
        )
        conn.execute(
            """INSERT OR REPLACE INTO transcription_queue (item_id, priority_score, queued_at)
               VALUES (?, 999, datetime('now'))""",
            (row["id"],)
        )
        print(f"  ✓ Prioriterad: {(row['title'] or '—')[:60]}")
    conn.commit()
    print(f"\n  {len(selected)} objekt boostad till toppen av kön.")


def clear_queue(conn, domain: str = None, state: str = None) -> None:
    """
    Rensar kön genom att återställa objekt till 'discovered'.
    domain: begränsa till domän. state: begränsa till ett tillstånd.
    """
    print("\n🗑️  Rensa kö")
    print("─" * 50)

    state_filter = state or "queued"
    query_info = """
        SELECT state, COUNT(*) as n FROM vigil_items
        WHERE state IN ('queued','filtered_in','transcribed','indexed')
        {}
        GROUP BY state ORDER BY state
    """.format("AND domain = ?" if domain else "")
    params = (domain,) if domain else ()
    rows = conn.execute(query_info, params).fetchall()

    if not rows:
        print("  Ingenting att rensa.")
        return

    print("  Nuvarande tillstånd:")
    for r in rows:
        print(f"    {r['state']:<20} {r['n']} objekt")

    print()
    print("  Vad vill du rensa?")
    print("    1. Bara kön (queued → discovered)")
    print("    2. Allt utom indexerade (queued+filtered_in → discovered)")
    print("    3. Allt — börja helt om (alla → discovered)")
    print("    q. Avbryt")

    val = input("  Val: ").strip().lower()

    if val == "1":
        states_to_reset = ["queued"]
    elif val == "2":
        states_to_reset = ["queued", "filtered_in", "transcribed"]
    elif val == "3":
        states_to_reset = ["queued", "filtered_in", "transcribed", "indexed", "notified"]
    else:
        print("  Avbröts.")
        return

    placeholders = ",".join("?" * len(states_to_reset))
    domain_clause = "AND domain = ?" if domain else ""
    params_reset = states_to_reset + ([domain] if domain else [])

    conn.execute(
        f"UPDATE vigil_items SET state='discovered', priority_score=NULL, "
        f"transcript_path=NULL, whisper_segment=NULL "
        f"WHERE state IN ({placeholders}) {domain_clause}",
        params_reset
    )
    conn.execute("DELETE FROM transcription_queue")
    conn.commit()
    print(f"  ✓ Klar. Kör '--run' för att filtrera om.")


def _interactive_menu():
    """Interaktiv meny för clio-vigil (används när inga CLI-argument ges)."""
    conn = init_db()

    MENU = [
        ("1", "Samla in",              "--run"),
        ("2", "Transkribera",          "--transcribe"),
        ("3", "Summera",               "--summarize"),
        ("4", "Indexera (RAG)",        "--index"),
        ("5", "Digest-mail",           "--digest"),
        ("6", "Statistik",             "--stats"),
        ("7", "Visa kö",               "--list-queued"),
        ("8", "Välj att transkribera", "--pick"),
        ("9", "Rensa kö",              "--clear-queue"),
        ("s", "Välj källa att hämta",  "--pick-source"),
        ("i", "Importera URL",         "--import-url"),
        ("p", "Räkna om prioriteter",  "--recompute-priorities"),
        ("q", "Tillbaka",              None),
    ]

    while True:
        # Hämta snabbstatistik för rubrikraden
        all_stats = stats(conn)
        total    = sum(all_stats.values())
        queued   = all_stats.get("queued", 0)
        indexed  = all_stats.get("indexed", 0)

        print("\n")
        print("─" * 58)
        print(f"  🔭 clio-vigil   {total} objekt  |  {queued} i kö  |  {indexed} indexerade")
        print("─" * 58)
        for key, label, _ in MENU:
            if key == "q":
                print(f"  {'q':>2}.  {label}")
            else:
                print(f"  {key:>2}.  {label}")
        print("─" * 58)

        try:
            val = input("  Välj: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if val == "q" or val == "":
            break

        match = next((m for m in MENU if m[0] == val), None)
        if not match:
            print("  Ogiltigt val.")
            continue

        _, label, flag = match
        if flag is None:
            break

        print(f"\nStartar {label}...")
        print("─" * 40)

        # Bygg args och kör via samma parser-logik
        sys.argv = [sys.argv[0], flag]
        conn.close()
        conn = init_db()

        try:
            if flag == "--run":
                for domain_id in get_all_domains():
                    try:
                        run_pipeline(conn, domain_id)
                    except Exception as e:
                        logger.error(f"Pipeline-fel [{domain_id}]: {e}", exc_info=True)
            elif flag == "--transcribe":
                from transcriber import run_transcription_queue
                counts = run_transcription_queue(conn)
                print(f"\n✓ {counts['completed']} klara, {counts['preempted']} preempterade, {counts['failed']} misslyckade")
            elif flag == "--summarize":
                from summarizer import run_summarizer
                counts = run_summarizer(conn)
                print(f"\n✓ {counts['done']} klara, {counts['failed']} misslyckade")
            elif flag == "--index":
                from indexer import run_indexer
                counts = run_indexer(conn)
                print(f"\n✓ {counts['indexed']} indexerade, {counts['failed']} misslyckade")
            elif flag == "--digest":
                from notifier import run_digest
                counts = run_digest(conn)
                print(f"\n✓ {counts['items']} objekt i digest")
            elif flag == "--stats":
                print_stats(conn)
            elif flag == "--list-queued":
                print_queued(conn)
            elif flag == "--pick":
                pick_items(conn)
            elif flag == "--clear-queue":
                clear_queue(conn)
            elif flag == "--recompute-priorities":
                from orchestrator import recompute_all_priorities
                n = recompute_all_priorities(conn)
                print(f"\n✓ Räknade om priority_score för {n} objekt (inkl. tidsfaktor)")
            elif flag == "--pick-source":
                pick_source(conn)
            elif flag == "--import-url":
                url = input("  URL (webb eller PDF): ").strip()
                dom = input("  Domän (ufo/ai): ").strip() or "ai"
                if url:
                    import_url(conn, url, dom)
        except KeyboardInterrupt:
            print("\n(Avbruten)")

        input("\nTryck Enter för att fortsätta...")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="clio-vigil — mediebevakning och intelligence-pipeline"
    )
    parser.add_argument("--run",         action="store_true", help="Kör collect+filter pipeline")
    parser.add_argument("--transcribe",  action="store_true", help="Kör transkriptionskö")
    parser.add_argument("--summarize",   action="store_true", help="Kör summering (Claude)")
    parser.add_argument("--index",       action="store_true", help="Kör RAG-indexering (Qdrant)")
    parser.add_argument("--digest",      action="store_true", help="Skicka daglig digest-mail")
    parser.add_argument("--full",        action="store_true", help="Kör hela pipeline: run+transcribe+summarize+index+digest")
    parser.add_argument("--stats",       action="store_true", help="Visa tillståndsstatistik")
    parser.add_argument("--list-queued",  action="store_true", help="Lista transkriptionskön")
    parser.add_argument("--pick",         action="store_true", help="Välj objekt att prioritera i kön")
    parser.add_argument("--clear-queue",          action="store_true", help="Rensa kön (återställ tillstånd)")
    parser.add_argument("--pick-source",          action="store_true", help="Välj vilken källa som ska hämtas in")
    parser.add_argument("--recompute-priorities", action="store_true", help="Räkna om priority_score för alla objekt (inkl. ny tidsfaktor)")
    parser.add_argument("--import-url",   type=str,            help="Importera webb-sida eller PDF direkt")
    parser.add_argument("--classify-uap", action="store_true", help="Klassificera queued UFO-items och skapa pending Odoo-encounters")
    parser.add_argument("--seed-sources", action="store_true", help="Importera YAML-källkonfiguration till Odoo (engångsimport)")
    parser.add_argument("--domain",      type=str,            help="Begränsa till domän (t.ex. ufo)")
    parser.add_argument("--all-domains", action="store_true", help="Kör alla konfigurerade domäner")
    parser.add_argument("--dry-run",     action="store_true", help="Simulera utan sändning (digest)")
    parser.add_argument("--max",         type=int, default=10, help="Max objekt per steg (default: 10)")

    args = parser.parse_args()

    any_action = any([
        args.run, args.transcribe, args.summarize, args.index,
        args.digest, args.full, args.stats, args.list_queued,
        args.pick, args.clear_queue, args.pick_source, bool(args.import_url),
        args.recompute_priorities, args.classify_uap, args.seed_sources,
    ])
    if not any_action:
        _interactive_menu()
        sys.exit(0)

    conn = init_db()

    # Odoo-anslutning (mjukt beroende — körningen fortsätter utan)
    try:
        from odoo_writer import get_odoo_env, sync_items_from_conn, write_sources, write_heartbeat
        _odoo_env = get_odoo_env()
    except Exception as _e:
        logger.warning("odoo_writer saknas eller anslutning misslyckades: %s", _e)
        _odoo_env = None

    def _odoo_sync(label: str = "") -> None:
        """Synkar aktuella pipeline-objekt till Odoo. Kraschsäkert."""
        if _odoo_env is None:
            return
        try:
            n = sync_items_from_conn(_odoo_env, conn)
            if n:
                logger.info("Odoo-sync %s: %d objekt", label, n)
        except Exception as _se:
            logger.warning("Odoo-sync misslyckades (%s): %s", label, _se)

    if args.seed_sources:
        if _odoo_env is None:
            logger.error("--seed-sources kräver Odoo-anslutning.")
        else:
            all_sources = []
            for domain_id in get_all_domains():
                try:
                    cfg = load_domain_config(domain_id)
                except Exception:
                    continue
                for s in cfg.get("sources", {}).get("rss", []):
                    all_sources.append({**s, "domain": domain_id, "source_type": "rss"})
                for s in cfg.get("sources", {}).get("youtube_channels", []):
                    url = s.get("channel_id", "")
                    if url and not url.startswith("http"):
                        url = f"https://www.youtube.com/{url}"
                    all_sources.append({
                        **s, "url": url,
                        "domain": domain_id, "source_type": "youtube",
                    })
            n = write_sources(_odoo_env, all_sources)
            print(f"✓ {n} källor importerade till Odoo.")

    if args.stats:
        print_stats(conn, args.domain)

    elif args.list_queued:
        print_queued(conn, args.domain)

    elif args.pick:
        pick_items(conn, args.domain)

    elif args.clear_queue:
        clear_queue(conn, args.domain)

    elif args.pick_source:
        pick_source(conn)

    elif args.import_url:
        import_url(conn, args.import_url, args.domain or "ai")

    elif args.recompute_priorities:
        from orchestrator import recompute_all_priorities
        n = recompute_all_priorities(conn)
        print(f"\n✓ Räknade om priority_score för {n} objekt (inkl. tidsfaktor)")

    elif args.run or args.full:
        domains = get_all_domains() if args.all_domains else [args.domain or "ufo"]
        for domain_id in domains:
            try:
                run_pipeline(conn, domain_id)
            except FileNotFoundError as e:
                logger.error(e)
            except Exception as e:
                logger.error(f"Pipeline-fel [{domain_id}]: {e}", exc_info=True)
        _odoo_sync("efter filter")

    if args.transcribe or args.full:
        from transcriber import run_transcription_queue
        counts = run_transcription_queue(conn, domain=args.domain, max_items=args.max)
        logger.info(
            f"Transkription: {counts['completed']} klara, "
            f"{counts['preempted']} preempterade, {counts['failed']} misslyckade"
        )
        _odoo_sync("efter transkription")

    if args.summarize or args.full:
        from summarizer import run_summarizer
        counts = run_summarizer(conn, domain=args.domain, max_items=args.max)
        logger.info(f"Summering: {counts['done']} klara, {counts['failed']} misslyckade")
        _odoo_sync("efter summering")

    if args.index or args.full:
        from indexer import run_indexer
        counts = run_indexer(conn, domain=args.domain, max_items=args.max)
        logger.info(f"Indexering: {counts['indexed']} indexerade, {counts['failed']} misslyckade")
        _odoo_sync("efter indexering")

    if args.classify_uap or args.full:
        import sys as _sys, os as _os
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).parent.parent / "clio-uap"))
        _sys.path.insert(0, str(_Path(__file__).parent.parent))
        from classifiers.uap_pipeline import run_uap_classifier
        try:
            import sys as _s2
            _s2.path.insert(0, str(_Path(__file__).parent.parent / "clio_odoo"))
            from clio_odoo import connect as _odoo_connect
            _odoo_env = _odoo_connect()
        except Exception as _e:
            logger.error(f"Odoo-anslutning misslyckades: {_e}")
            _odoo_env = None
        if _odoo_env or args.dry_run:
            counts = run_uap_classifier(conn, _odoo_env, max_items=args.max, dry_run=args.dry_run)
            logger.info(
                f"UAP-klassificering: {counts['classified']} klassificerade, "
                f"{counts['imported']} importerade till Odoo"
            )

    if args.digest or args.full:
        from notifier import run_digest
        counts = run_digest(conn, domain=args.domain, dry_run=args.dry_run)
        logger.info(f"Digest: {counts['items']} objekt skickade")
        _odoo_sync("efter digest")

    # Heartbeat — alltid vid körning med pipeline-steg
    if _odoo_env is not None and any([
        args.run, args.transcribe, args.summarize,
        args.index, args.digest, args.full,
    ]):
        try:
            total = sum(conn.execute("SELECT COUNT(*) FROM vigil_items").fetchone())
            write_heartbeat(_odoo_env, status="ok", items_processed=total,
                            message=f"{total} objekt i vigil.db")
        except Exception as _he:
            logger.warning("Heartbeat misslyckades: %s", _he)

    conn.close()


if __name__ == "__main__":
    main()
