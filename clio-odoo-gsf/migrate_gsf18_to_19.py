"""
migrate_gsf18_to_19.py - Engangsmigrering: kontakter, taggar, relationstyper och
relationer fran gsf pa Odoo 18 till en ny, tom gsf-databas pa Odoo 19.

Kraver:
- Kalldatabasens .env: ../../18.0/clio-tools/clio-odoo-gsf/.env (ODOO_URL/DB/USER/PASSWORD)
- Maldatabasens .env: samma katalog som detta script (redan skapad)

Korning:
    python3 migrate_gsf18_to_19.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).parent.parent))
from clio_odoo import connect

SRC_ENV = Path("/home/clioadmin/18.0/clio-tools/clio-odoo-gsf/.env")
DST_ENV = Path(__file__).parent / ".env"


PARTNER_SCALAR_FIELDS = [
    "name", "is_company", "ref", "street", "street2", "zip", "city",
    "email", "phone", "comment", "personnummer",
    "social_linkedin", "social_twitter", "social_facebook",
    "social_instagram", "social_github",
]
PARTNER_READ_FIELDS = PARTNER_SCALAR_FIELDS + ["mobile", "category_id", "country_id"]


def _to_int(v):
    return v.id if hasattr(v, "id") else int(v)


def _m2o_id(v):
    if not v:
        return None
    if isinstance(v, (list, tuple)):
        return int(v[0])
    return _to_int(v)


def _m2m_ids(v):
    if not v:
        return []
    return [int(x) if not hasattr(x, "id") else _to_int(x) for x in v]


def connect_source():
    vals = dotenv_values(SRC_ENV)
    return connect(
        url=vals["ODOO_URL"], db=vals["ODOO_DB"],
        user=vals["ODOO_USER"], password=vals["ODOO_PASSWORD"],
    )


def migrate_tags(src, dst) -> dict[int, int]:
    SrcTag, DstTag = src["res.partner.category"], dst["res.partner.category"]
    tag_map = {}
    for row in SrcTag.search_read([], ["id", "name"]):
        hits = DstTag.search_read([("name", "=", row["name"])], ["id"])
        tag_map[row["id"]] = _to_int(hits[0]["id"]) if hits else _to_int(DstTag.create({"name": row["name"]}))
    print(f"Taggar: {len(tag_map)} mappade")
    return tag_map


def build_country_mapper(src, dst):
    SrcCountry, DstCountry = src["res.country"], dst["res.country"]
    cache: dict[int, int | None] = {}

    def map_country(src_id):
        if not src_id:
            return None
        if src_id not in cache:
            hit = SrcCountry.search_read([("id", "=", src_id)], ["code"])
            code = hit[0]["code"] if hit else None
            dst_hit = DstCountry.search_read([("code", "=", code)], ["id"]) if code else []
            cache[src_id] = _to_int(dst_hit[0]["id"]) if dst_hit else None
        return cache[src_id]

    return map_country


def migrate_partners(src, dst, tag_map, dry_run: bool) -> dict[int, int]:
    SrcPartner, DstPartner = src["res.partner"], dst["res.partner"]
    map_country = build_country_mapper(src, dst)
    partner_map: dict[int, int] = {}
    created = updated = errors = 0

    for row in SrcPartner.search_read([], PARTNER_READ_FIELDS):
        vals = {k: row[k] for k in PARTNER_SCALAR_FIELDS if row.get(k) not in (False, None)}
        vals["is_company"] = bool(row.get("is_company"))

        # Odoo 19 res.partner har inget eget 'mobile'-falt langre - bara 'phone'.
        # Foredra befintligt phone; annars anvand mobile. Om bada finns, notera
        # mobilnumret i comment sa ingen data forsvinner tyst.
        mobile = row.get("mobile") or None
        if mobile:
            if vals.get("phone"):
                note = f"Mobil: {mobile}"
                vals["comment"] = f"{vals['comment']}\n{note}" if vals.get("comment") else note
            else:
                vals["phone"] = mobile
        tag_ids = _m2m_ids(row.get("category_id"))
        if tag_ids:
            vals["category_id"] = [(6, 0, [tag_map[t] for t in tag_ids if t in tag_map])]
        country_id = map_country(_m2o_id(row.get("country_id")))
        if country_id:
            vals["country_id"] = country_id

        if dry_run:
            print(f"  [DRY] {row['id']} -> {vals.get('name')}")
            created += 1
            continue

        try:
            new_id = None
            if vals.get("ref"):
                hits = DstPartner.search_read([("ref", "=", vals["ref"])], ["id"])
                if hits:
                    new_id = _to_int(hits[0]["id"])
                    DstPartner.write(new_id, vals)
                    updated += 1
            if new_id is None:
                new_id = _to_int(DstPartner.create(vals))
                created += 1
            partner_map[row["id"]] = new_id
        except Exception as e:
            print(f"  FEL partner {row['id']} ({row.get('name')}): {e}")
            errors += 1

    print(f"Partners: {created} skapade, {updated} uppdaterade, {errors} fel, {len(partner_map)} mappade")
    return partner_map


def migrate_relation_types(src, dst, tag_map, dry_run: bool) -> dict[int, int]:
    SrcType, DstType = src["res.partner.relation.type"], dst["res.partner.relation.type"]
    fields = [
        "id", "name", "name_inverse", "contact_type_left", "contact_type_right",
        "partner_category_left", "partner_category_right", "allow_self", "is_symmetric",
    ]
    type_map: dict[int, int] = {}
    for row in SrcType.search_read([], fields):
        vals = {
            "name": row["name"],
            "name_inverse": row["name_inverse"],
            "left_partner_type": row.get("contact_type_left") or False,
            "right_partner_type": row.get("contact_type_right") or False,
            "allow_self": bool(row.get("allow_self")),
            "is_symmetric": bool(row.get("is_symmetric")),
        }
        left_cat = _m2o_id(row.get("partner_category_left"))
        if left_cat and left_cat in tag_map:
            vals["left_partner_category_id"] = tag_map[left_cat]
        right_cat = _m2o_id(row.get("partner_category_right"))
        if right_cat and right_cat in tag_map:
            vals["right_partner_category_id"] = tag_map[right_cat]

        if dry_run:
            print(f"  [DRY] typ {row['id']} -> {vals['name']}")
            type_map[row["id"]] = row["id"]
            continue

        type_map[row["id"]] = _to_int(DstType.create(vals))

    print(f"Relationstyper: {len(type_map)} mappade")
    return type_map


def migrate_relations(src, dst, partner_map, type_map, dry_run: bool) -> None:
    SrcRel, DstRel = src["res.partner.relation"], dst["res.partner.relation"]
    fields = ["id", "left_partner_id", "right_partner_id", "type_id", "date_start", "date_end"]
    created = skipped = errors = 0

    for row in SrcRel.search_read([], fields):
        left = partner_map.get(_m2o_id(row.get("left_partner_id")))
        right = partner_map.get(_m2o_id(row.get("right_partner_id")))
        type_id = type_map.get(_m2o_id(row.get("type_id")))
        if not (left and right and type_id):
            print(f"  HOPPAR relation {row['id']}: saknar mappning (left={left} right={right} type={type_id})")
            skipped += 1
            continue

        vals = {"left_partner_id": left, "right_partner_id": right, "type_id": type_id}
        if row.get("date_start"):
            vals["date_start"] = row["date_start"]
        if row.get("date_end"):
            vals["date_end"] = row["date_end"]

        if dry_run:
            print(f"  [DRY] relation {row['id']} -> {vals}")
            created += 1
            continue

        try:
            DstRel.create(vals)
            created += 1
        except Exception as e:
            print(f"  FEL relation {row['id']}: {e}")
            errors += 1

    print(f"Relationer: {created} skapade, {skipped} hoppade, {errors} fel")


def connect_target():
    vals = dotenv_values(DST_ENV)
    return connect(
        url=vals["ODOO_URL"], db=vals["ODOO_DB"],
        user=vals["ODOO_USER"], password=vals["ODOO_PASSWORD"],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Migrera gsf-data fran Odoo 18 till ny Odoo 19-databas")
    parser.add_argument("--dry-run", action="store_true", help="Skriv inget till maldatabasen")
    args = parser.parse_args(argv)

    print("Ansluter till kalldatabas (18)...")
    src = connect_source()
    print("Ansluter till maldatabas (19)...")
    dst = connect_target()

    tag_map = migrate_tags(src, dst)
    partner_map = migrate_partners(src, dst, tag_map, args.dry_run)
    type_map = migrate_relation_types(src, dst, tag_map, args.dry_run)
    migrate_relations(src, dst, partner_map, type_map, args.dry_run)


if __name__ == "__main__":
    main()
