"""Import av begravningspsalmer från begravningspsalmer.json → clio.reco.item (item_type=link).

Upsert-nyckel: spotify_url (primär), annars psalm_nr.
Kör: python import_psalms.py [--dry-run] [--file /annan/sökväg.json]
"""
import argparse
import json
import sys
from pathlib import Path

from odoo_client import ODOO_DB, ODOO_PASSWORD, connect, ensure_genre

DEFAULT_JSON = Path(__file__).parent.parent.parent.parent / (
    "Dropbox/projekt/Clio-projekt/Clio_Reco/begravningspsalmer.json"
)

FIXED_GENRE = "Begravningspsalm"


def build_description(track: dict) -> str:
    parts = []
    if track.get("subtitle"):
        parts.append(f"<p><i>{track['subtitle']}</i></p>")
    if track.get("theme"):
        parts.append(f"<p><b>Tema:</b> {track['theme']}</p>")
    if track.get("mood"):
        parts.append(f"<p><b>Stämning:</b> {track['mood']}</p>")
    if track.get("begravning_rank"):
        parts.append(f"<p><b>Popularitet:</b> {track['begravning_rank']}</p>")
    if track.get("notes"):
        parts.append(f"<p>{track['notes']}</p>")
    return "".join(parts)


def upsert_psalm(models, uid, track: dict, genre_cache: dict, dry_run: bool) -> str:
    psalm_nr = track.get("psalm_nr")
    title = track["title"].strip()
    name = f"{title} (nr {psalm_nr})" if psalm_nr else title
    url = track.get("spotify_url", "").strip()
    composer = track.get("composer_text", "").strip()

    domain = [["item_type", "=", "link"]]
    if url:
        domain.append(["url", "=", url])
    elif psalm_nr:
        domain.append(["name", "ilike", f"nr {psalm_nr}"])

    existing = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "clio.reco.item", "search", [domain]) if not dry_run else []

    # Alltid genre "Begravningspsalm" + ev. specifik genre
    genre_ids = []
    for gname in [FIXED_GENRE, track.get("genre", "").strip()]:
        if not gname or gname == FIXED_GENRE and track.get("genre") == "Psalm":
            gname = FIXED_GENRE
        if gname and gname not in genre_cache:
            genre_cache[gname] = ensure_genre(models, uid, gname) if not dry_run else -1
        if gname and genre_cache.get(gname, -1) > 0:
            genre_ids.append((4, genre_cache[gname]))

    vals = {
        "name": name,
        "item_type": "link",
        "author": composer or False,
        "url": url or False,
        "description": build_description(track),
        "genre_ids": genre_ids,
        "is_published": True,
    }

    if dry_run:
        action = "UPDATE" if existing else "CREATE"
        print(f"  [{action}] {name}")
        return action.lower()

    if existing:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "clio.reco.item", "write", [existing, vals])
        return "updated"
    else:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "clio.reco.item", "create", [vals])
        return "created"


def main():
    parser = argparse.ArgumentParser(description="Importera begravningspsalmer till clio_reco")
    parser.add_argument("--dry-run", action="store_true", help="Simulera utan att skriva till Odoo")
    parser.add_argument("--file", default=str(DEFAULT_JSON), help="Sökväg till JSON-fil")
    args = parser.parse_args()

    json_path = Path(args.file)
    if not json_path.exists():
        print(f"Filen hittades inte: {json_path}")
        sys.exit(1)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    tracks = data.get("tracks", [])
    print(f"Läser {len(tracks)} psalmer från {json_path.name}")

    uid, models = (None, None) if args.dry_run else connect()
    if args.dry_run:
        print("[DRY RUN — inga ändringar skrivs]")

    genre_cache: dict = {}
    counts = {"created": 0, "updated": 0}

    for track in tracks:
        result = upsert_psalm(models, uid, track, genre_cache, args.dry_run)
        if result in counts:
            counts[result] += 1

    print(f"\nKlart: {counts['created']} skapade, {counts['updated']} uppdaterade")


if __name__ == "__main__":
    main()
