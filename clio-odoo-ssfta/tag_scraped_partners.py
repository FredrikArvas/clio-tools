"""
tag_scraped_partners.py — Taggar skrapade partner-poster som inte matchats till SSFTA.

Identifierar res.partner (is_company=False) som:
  - Saknar ssfta-person- prefix på ref
  - Har minst en roll-tagg (Ordförande, Kassör, etc.) — indikerar att de kommit från skidor.com
  - Är INTE redan taggade med SSFTA:Person (då är de synkade från SSFTA)

Lägger till taggarna:
  - Skrapad:skidor.com
  - EjMatchad

Körning:
    python tag_scraped_partners.py             # live
    python tag_scraped_partners.py --dry-run
    python tag_scraped_partners.py --db ssf_t2
"""

from __future__ import annotations
import argparse, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

ROLE_TAGS = {
    "Ordförande", "Vice Ordförande", "Kassör", "Sekreterare",
    "Styrelseledamot", "Ledamot", "Tränare", "Ungdomsledare",
    "Kontaktperson",
}

TAG_SCRAPED  = "Skrapad:skidor.com"
TAG_UNMATCHED = "EjMatchad"
BATCH_SIZE   = 500


def _to_int(val) -> int:
    if isinstance(val, (list, tuple)):
        return int(val[0])
    return val.id if hasattr(val, "id") else int(val)


def _get_or_create_tag(env, name: str) -> int:
    Cat = env["res.partner.category"]
    hits = Cat.search_read([("name", "=", name)], ["id"])
    return _to_int(hits[0]["id"]) if hits else _to_int(Cat.create({"name": name}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    print("Ansluter till Odoo...")
    env = connect(db=args.db or os.environ.get("ODOO_SSF_DB", "ssf"))
    print("  Ansluten till " + env.db)

    Partner = env["res.partner"]
    Cat     = env["res.partner.category"]

    # Hämta alla roll-tagg-IDs
    role_tag_ids = set()
    for tag_name in ROLE_TAGS:
        hits = Cat.search_read([("name", "=", tag_name)], ["id"])
        if hits:
            role_tag_ids.add(_to_int(hits[0]["id"]))
    print("  " + str(len(role_tag_ids)) + " roll-taggar hittade: " + str(ROLE_TAGS & {t for t in ROLE_TAGS}))

    if not role_tag_ids:
        print("  Inga roll-taggar hittades — avslutar.")
        return

    # Hämta tagg-ID för SSFTA:Person (uteslutningskriterium)
    ssfta_person_hits = Cat.search_read([("name", "=", "SSFTA:Person")], ["id"])
    ssfta_person_tag_id = _to_int(ssfta_person_hits[0]["id"]) if ssfta_person_hits else None

    # Hämta kandidater: is_company=False, har minst en roll-tagg,
    # saknar ssfta-person- prefix och SSFTA:Person-tagg
    domain = [
        ("is_company", "=", False),
        ("active", "in", [True, False]),
        ("category_id", "in", list(role_tag_ids)),
    ]
    if ssfta_person_tag_id:
        domain.append(("category_id", "not in", [ssfta_person_tag_id]))

    candidates = Partner.search_read(domain, ["id", "ref", "name", "category_id"])
    print("  " + str(len(candidates)) + " kandidater med roll-taggar (exkl. SSFTA:Person).")

    # Filtrera bort de som har ssfta-person- prefix
    to_tag = []
    for p in candidates:
        ref = (p.get("ref") or "")
        if not ref.startswith("ssfta-person-"):
            to_tag.append(_to_int(p["id"]))

    print("  " + str(len(to_tag)) + " poster att tagga (utan ssfta-person- ref).")

    if args.dry_run:
        print("  Exempel (topp 10):")
        for p in candidates[:10]:
            ref = p.get("ref") or "(ingen ref)"
            print("    " + str(_to_int(p["id"])) + " | " + ref + " | " + str(p.get("name", "")))
        print("  (--dry-run, ingen data skrevs)")
        return

    if not to_tag:
        print("  Inget att göra.")
        return

    # Hämta/skapa tagg-IDs
    scraped_tid   = _get_or_create_tag(env, TAG_SCRAPED)
    unmatched_tid = _get_or_create_tag(env, TAG_UNMATCHED)
    print("  Taggar: " + TAG_SCRAPED + " (id=" + str(scraped_tid) + "), " +
          TAG_UNMATCHED + " (id=" + str(unmatched_tid) + ")")

    # Sätt taggar i batchar
    tagged = errors = 0
    for i in range(0, len(to_tag), BATCH_SIZE):
        batch = to_tag[i:i + BATCH_SIZE]
        try:
            Partner.write(batch, {
                "category_id": [(4, scraped_tid), (4, unmatched_tid)],
                "active": True,  # arkiverade poster aktiveras för synlighet
            })
            tagged += len(batch)
        except Exception as e:
            print("  FEL (batch " + str(i) + "): " + str(e)[:80])
            errors += len(batch)

    print("\nKlar:")
    print("  " + str(tagged) + " poster taggade med " + TAG_SCRAPED + " + " + TAG_UNMATCHED)
    print("  " + str(errors) + " fel")


if __name__ == "__main__":
    main()
