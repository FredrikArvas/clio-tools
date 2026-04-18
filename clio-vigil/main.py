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
import socket as _socket
_orig_getaddrinfo = _socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if family == 0:
        family = _socket.AF_INET
    return _orig_getaddrinfo(host, port, family, type, proto, flags)
_socket.getaddrinfo = _ipv4_getaddrinfo

import yaml

from orchestrator import init_db, stats, domain_stats
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


def _interactive_menu():
    """Interaktiv meny för clio-vigil (används när inga CLI-argument ges)."""
    conn = init_db()

    MENU = [
        ("1", "Samla in",       "--run"),
        ("2", "Transkribera",   "--transcribe"),
        ("3", "Summera",        "--summarize"),
        ("4", "Indexera (RAG)", "--index"),
        ("5", "Digest-mail",    "--digest"),
        ("6", "Statistik",      "--stats"),
        ("7", "Visa kö",        "--list-queued"),
        ("q", "Tillbaka",       None),
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
    parser.add_argument("--list-queued", action="store_true", help="Lista transkriptionskön")
    parser.add_argument("--domain",      type=str,            help="Begränsa till domän (t.ex. ufo)")
    parser.add_argument("--all-domains", action="store_true", help="Kör alla konfigurerade domäner")
    parser.add_argument("--dry-run",     action="store_true", help="Simulera utan sändning (digest)")
    parser.add_argument("--max",         type=int, default=10, help="Max objekt per steg (default: 10)")

    args = parser.parse_args()

    any_action = any([
        args.run, args.transcribe, args.summarize, args.index,
        args.digest, args.full, args.stats, args.list_queued,
    ])
    if not any_action:
        _interactive_menu()
        sys.exit(0)

    conn = init_db()

    if args.stats:
        print_stats(conn, args.domain)

    elif args.list_queued:
        print_queued(conn, args.domain)

    elif args.run or args.full:
        domains = get_all_domains() if args.all_domains else [args.domain or "ufo"]
        for domain_id in domains:
            try:
                run_pipeline(conn, domain_id)
            except FileNotFoundError as e:
                logger.error(e)
            except Exception as e:
                logger.error(f"Pipeline-fel [{domain_id}]: {e}", exc_info=True)

    if args.transcribe or args.full:
        from transcriber import run_transcription_queue
        counts = run_transcription_queue(conn, domain=args.domain, max_items=args.max)
        logger.info(
            f"Transkription: {counts['completed']} klara, "
            f"{counts['preempted']} preempterade, {counts['failed']} misslyckade"
        )

    if args.summarize or args.full:
        from summarizer import run_summarizer
        counts = run_summarizer(conn, domain=args.domain, max_items=args.max)
        logger.info(f"Summering: {counts['done']} klara, {counts['failed']} misslyckade")

    if args.index or args.full:
        from indexer import run_indexer
        counts = run_indexer(conn, domain=args.domain, max_items=args.max)
        logger.info(f"Indexering: {counts['indexed']} indexerade, {counts['failed']} misslyckade")

    if args.digest or args.full:
        from notifier import run_digest
        counts = run_digest(conn, domain=args.domain, dry_run=args.dry_run)
        logger.info(f"Digest: {counts['items']} objekt skickade")

    conn.close()


if __name__ == "__main__":
    main()
