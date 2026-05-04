"""
research.py — CLI entry point för clio-research.

Användning (Windows PowerShell):
  python research.py --gedcom-id "@I192@" --gedcom-file "path\to\fil.ged" --syfte guldboda-75
  python research.py --gedcom-id "@I192@" --gedcom-file "path\to\fil.ged" --dry-run
  python research.py --approve REVIEW-xxx
  python research.py --batch --gedcom-file "path\to\fil.ged" --filter-surname Arvas --syfte guldboda-75
  python research.py --status
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from pathlib import Path as _Path

# Ladda clio-tools/.env (parent) som bas, sedan lokal .env som override
load_dotenv(_Path(__file__).parent.parent / ".env")
load_dotenv(override=False)  # lokal .env lägger bara till, skriver ej över

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("clio-research")


def _require_notion_token() -> str:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token or token == "secret_xxx":
        logger.error(
            "NOTION_TOKEN saknas eller är placeholder. "
            "Sätt variabeln i .env eller miljön."
        )
        sys.exit(1)
    return token


def _resolve_gedcom(gedcom_file: str) -> Path:
    p = Path(gedcom_file)
    if not p.exists():
        logger.error("GEDCOM-fil hittades inte: %s", p)
        sys.exit(1)
    return p


def cmd_run(args: argparse.Namespace) -> None:
    """Kör pipeline för en enskild person."""
    from pipeline import ResearchPipeline
    from notion_writer import NotionWriter

    gedcom_path = _resolve_gedcom(args.gedcom_file)
    pipeline = ResearchPipeline(gedcom_path=gedcom_path)

    levande = getattr(args, "levande", None)  # "ja" | "nej" | "vet-ej" | None
    logger.info("Startar pipeline för %s ...", args.gedcom_id)
    result = pipeline.run(gedcom_id=args.gedcom_id, syfte=args.syfte or "", levande_override=levande)

    if result.errors:
        for err in result.errors:
            logger.warning("Fel: %s", err)

    if result.person_record is None:
        logger.error("Ingen personpost skapades - avbryter")
        sys.exit(1)

    # Alltid visa JSON-sammanfattning
    record_dict = result.person_record.to_dict()
    print("\n" + "=" * 60)
    print(f"Person: {result.person_record.fornamn.värde} {result.person_record.efternamn.värde}")
    print(f"GDPR-flaggad: {result.gdpr_flagged}")
    print(f"Behöver granskning: {result.needs_review}")
    if result.review_items:
        print("Granskningsfält:")
        for fält, fv in result.review_items:
            print(f"  {fält}: {fv.värde!r} (konf={fv.konfidens:.2f})")
    if result.wikidata_multiple_candidates:
        print(f"Wikidata: {len(result.wikidata_candidates)} kandidater — kräver granskning")

    if args.dry_run:
        print("\n[dry-run] JSON-output:")
        print(json.dumps(record_dict, ensure_ascii=False, indent=2))
        print("\n[dry-run] Ingenting sparades till Notion.")
        return

    token = _require_notion_token()
    writer = NotionWriter(notion_token=token)

    # Spara personpost
    page_id = writer.write_person(result)
    if page_id:
        logger.info("Personpost sparad: %s", page_id)

    # Skapa alltid granskningskort när en person sparas (status=Utkast)
    if page_id:
        review_id = writer.create_review_card(result)
        if review_id:
            logger.info("Granskningskort skapat: %s", review_id)


def cmd_batch(args: argparse.Namespace) -> None:
    """Kör pipeline för alla personer med givet efternamn."""
    from pipeline import ResearchPipeline
    from notion_writer import NotionWriter
    from sources.gedcom import GedcomSource

    gedcom_path = _resolve_gedcom(args.gedcom_file)
    gs = GedcomSource(gedcom_path)

    if args.filter_surname:
        persons = gs.search_by_surname(args.filter_surname)
    else:
        persons = [gs.get_person(gid) for gid in gs.list_ids() if gs.get_person(gid)]

    logger.info("Batch: %d personer att bearbeta", len(persons))

    pipeline = ResearchPipeline(gedcom_path=gedcom_path)
    token = None if args.dry_run else _require_notion_token()
    writer = None if args.dry_run else NotionWriter(notion_token=token)

    for i, person in enumerate(persons, 1):
        logger.info("[%d/%d] %s %s (%s)", i, len(persons),
                    person.fornamn or "", person.efternamn or "", person.gedcom_id)
        result = pipeline.run(gedcom_id=person.gedcom_id, syfte=args.syfte or "")

        if not args.dry_run and result.person_record:
            batch_page_id = writer.write_person(result)
            if batch_page_id:
                writer.create_review_card(result)
        elif args.dry_run and result.person_record:
            print(f"[dry-run] {person.fornamn} {person.efternamn}: "
                  f"granskning={result.needs_review}, GDPR={result.gdpr_flagged}")

    logger.info("Batch klar: %d personer bearbetade", len(persons))


def _notion_url(page_id: str) -> str:
    """Konverterar Notion page ID till klickbar URL."""
    return "https://www.notion.so/" + page_id.replace("-", "")


def cmd_status(args: argparse.Namespace) -> None:
    """Visa väntande granskningskort med klickbara Notion-URLs och interaktivt godkännande."""
    token = _require_notion_token()
    from notion_writer import NotionWriter
    from notion_client import Client

    writer = NotionWriter(notion_token=token)
    client = Client(auth=token)

    while True:
        pending = writer.list_pending_reviews()
        if not pending:
            print("Inga väntande granskningskort.")
            return

        print(f"\n{len(pending)} väntande granskningskort:\n")
        for i, p in enumerate(pending, 1):
            print(f"  {i}. {p['title']}")
            print(f"     {_notion_url(p['id'])}")

        print()
        raw = input("Välj nummer att godkänna (0=tillbaka, t.ex. 1 / 1-3 / all): ").strip()
        if not raw or raw == "0":
            return

        ids = _parse_approve_ids(raw, pending)
        print()
        ok = sum(_approve_one(client, rid, pending) for rid in ids)
        print(f"\n{ok}/{len(ids)} granskningskort godkända.")

        remaining = writer.list_pending_reviews()
        if not remaining:
            print("Alla granskningskort godkända!")
            return


def _approve_one(client, review_id: str, pending: list[dict]) -> bool:
    """Godkänner ett enskilt kort. Returns True vid framgång.

    Granskningskort (source=granskning): lägger till ✅ i titeln.
    Personregister-utkast (source=register): sätter Status → Publicerad.
    """
    from notion_client.errors import APIResponseError

    rid = review_id.strip()
    source = "granskning"
    if rid.isdigit():
        idx = int(rid) - 1
        if not (0 <= idx < len(pending)):
            logger.error("Ogiltigt nummer: %s (finns %d kort)", rid, len(pending))
            return False
        p = pending[idx]
        rid = p["id"]
        source = p.get("source", "granskning")
        logger.info("Godkänner: %s", p["title"])

    try:
        if source == "register":
            client.pages.update(
                page_id=rid,
                properties={"Status": {"select": {"name": "Publicerad"}}},
            )
        else:
            page = client.pages.retrieve(page_id=rid)
            title_parts = page.get("properties", {}).get("title", {}).get("title", [])
            current_title = "".join(t.get("plain_text", "") for t in title_parts)
            if not current_title.startswith("✅"):
                new_title = "✅ " + current_title
                client.pages.update(
                    page_id=rid,
                    properties={"title": [{"text": {"content": new_title}}]},
                )
        print(f"  ✅ Klart: {_notion_url(rid)}")
        return True
    except APIResponseError as exc:
        logger.error("Kunde inte uppdatera %s: %s", rid, exc)
        return False


def _parse_approve_ids(raw: str, pending: list[dict]) -> list[str]:
    """
    Tolkar godkännandespec till lista av strängar (nummer eller Notion-ID:n).

    Stöder:
      "all"     → alla väntande
      "1-11"    → nummer 1 t.o.m. 11
      "1,3,5"   → specifika nummer
      "1,3-5,7" → blandat
      "abc-123" → direkt Notion-ID
    """
    raw = raw.strip().lower()
    if raw == "all":
        return [str(i + 1) for i in range(len(pending))]

    result = []
    for part in raw.split(","):
        part = part.strip()
        # Intervall t.ex. "1-11" (bara om båda sidorna är siffror)
        range_m = re.match(r"^(\d+)-(\d+)$", part)
        if range_m:
            start, end = int(range_m.group(1)), int(range_m.group(2))
            result.extend(str(n) for n in range(start, end + 1))
        else:
            result.append(part)
    return result


def _print_pending(pending: list[dict]) -> None:
    print(f"\n{len(pending)} vaentande granskningskort kvar:\n")
    for i, p in enumerate(pending, 1):
        print(f"  {i}. {p['title']}")
    print()


def cmd_approve(args: argparse.Namespace) -> None:
    """Markera ett eller flera granskningskort som klara."""
    token = _require_notion_token()
    from notion_writer import NotionWriter
    from notion_client import Client

    client = Client(auth=token)
    writer = NotionWriter(notion_token=token)
    pending = writer.list_pending_reviews()

    if not pending:
        print("Inga vaentande granskningskort.")
        return

    raw = args.review_id.strip()
    ids = _parse_approve_ids(raw, pending)

    print()
    ok = sum(_approve_one(client, rid, pending) for rid in ids)
    print(f"\n{ok}/{len(ids)} granskningskort godkaenda.")

    # Visa kvarvarande om det finns
    remaining = writer.list_pending_reviews()
    if remaining:
        _print_pending(remaining)
    else:
        print("Alla granskningskort godkaenda!")


def cmd_db(args: argparse.Namespace) -> None:
    """Visa URL till Notion Personregistret."""
    from notion_writer import NOTION_PERSONREGISTER_DB
    url = "https://www.notion.so/" + NOTION_PERSONREGISTER_DB.replace("-", "")
    print(f"\nNotion Personregister:\n  {url}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="research.py",
        description="clio-research — Persondata-pipeline (GEDCOM → Wikidata → Wikipedia → Libris → Notion)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- run (default, även utan subkommando) ---
    run_args = argparse.ArgumentParser(add_help=False)
    run_args.add_argument("--gedcom-id", required=True, help='GEDCOM-ID, t.ex. "@I192@"')
    run_args.add_argument("--gedcom-file", required=True, help="Sökväg till .ged-fil")
    run_args.add_argument("--syfte", default="", help="Sammanhangsetikett, t.ex. guldboda-75")
    run_args.add_argument("--dry-run", action="store_true", help="Skriv JSON till stdout, spara ej")

    # Subkommando: run
    sub_run = subparsers.add_parser("run", parents=[run_args], help="Kör pipeline för en person")
    sub_run.set_defaults(func=cmd_run)

    # Subkommando: batch
    sub_batch = subparsers.add_parser("batch", help="Kör pipeline för flera personer")
    sub_batch.add_argument("--gedcom-file", required=True)
    sub_batch.add_argument("--filter-surname", help="Filtrera på efternamn")
    sub_batch.add_argument("--syfte", default="")
    sub_batch.add_argument("--dry-run", action="store_true")
    sub_batch.set_defaults(func=cmd_batch)

    # Subkommando: status
    sub_status = subparsers.add_parser("status", help="Visa väntande granskningskort")
    sub_status.set_defaults(func=cmd_status)

    # Subkommando: approve
    sub_approve = subparsers.add_parser("approve", help="Godkänn ett eller flera granskningskort")
    sub_approve.add_argument("review_id", help="Nummer eller ID, kommaseparerat (t.ex. '1,3')")
    sub_approve.set_defaults(func=cmd_approve)

    # Subkommando: db
    sub_db = subparsers.add_parser("db", help="Visa URL till Notion Personregistret")
    sub_db.set_defaults(func=cmd_db)

    # Stödj också direktanrop utan subkommando (bakåtkompatibilitet med SPEC.md)
    # python research.py --gedcom-id ... --dry-run
    parser.add_argument("--gedcom-id", help='GEDCOM-ID, t.ex. "@I192@"')
    parser.add_argument("--gedcom-file", help="Sökväg till .ged-fil")
    parser.add_argument("--syfte", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--levande", choices=["ja", "nej", "vet-ej"],
                        help="Är personen levande? (ja/nej/vet-ej)")
    parser.add_argument("--batch", action="store_true", help="Kör i batch-läge")
    parser.add_argument("--filter-surname", help="Filtrera på efternamn (batch)")
    parser.add_argument("--approve", metavar="REVIEW_ID", help="Godkänn granskningskort (kommaseparerat)")
    parser.add_argument("--status", action="store_true", help="Visa väntande granskningskort")
    parser.add_argument("--db", action="store_true", help="Visa URL till Notion Personregistret")

    args = parser.parse_args()

    # Direkt-anropsläge (utan subkommando)
    if args.command is None:
        if args.status:
            cmd_status(args)
        elif args.db:
            cmd_db(args)
        elif args.approve:
            args.review_id = args.approve
            cmd_approve(args)
        elif args.batch:
            cmd_batch(args)
        elif args.gedcom_id and args.gedcom_file:
            cmd_run(args)
        else:
            parser.print_help()
            sys.exit(1)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
