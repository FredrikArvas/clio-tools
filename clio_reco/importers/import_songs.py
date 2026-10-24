"""Import av låtar från death_songs.json → clio.reco.item (item_type=link).

Upsert-nyckel: spotify_url.
Kör: python import_songs.py [--dry-run] [--file /annan/sökväg.json]
"""
import argparse
import json
import sys
from pathlib import Path

from odoo_client import ODOO_DB, ODOO_PASSWORD, connect, ensure_genre

DEFAULT_JSON = Path(__file__).parent.parent.parent.parent / (
    "Dropbox/projekt/Clio-projekt/Clio_Reco/death_songs.json"
)


def upsert_song(models, uid, track: dict, genre_cache: dict, dry_run: bool) -> str:
    title = track["title"].strip()
    artist = track.get("artist", "").strip()
    name = f"{title} — {artist}" if artist else title
    url = track.get("spotify_url", "").strip()
    genre_str = track.get("genre", "Övrigt").strip()
    theme = track.get("theme", "").strip()

    domain = [["item_type", "=", "link"]]
    if url:
        domain.append(["url", "=", url])
    else:
        domain.append(["name", "=", name])

    existing = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "clio.reco.item", "search", [domain]) if not dry_run else []

    # Hantera genre-strängar som kan innehålla slash (t.ex. "Rock/Folk")
    genre_names = [g.strip() for g in genre_str.replace("/", ",").split(",") if g.strip()]
    genre_ids = []
    for gname in genre_names:
        if gname not in genre_cache:
            genre_cache[gname] = ensure_genre(models, uid, gname) if not dry_run else -1
        if genre_cache[gname] > 0:
            genre_ids.append((4, genre_cache[gname]))

    description = f"<p><b>Tema:</b> {theme}</p>" if theme else ""

    vals = {
        "name": name,
        "item_type": "link",
        "author": artist or False,
        "url": url or False,
        "description": description,
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
    parser = argparse.ArgumentParser(description="Importera låtar till clio_reco")
    parser.add_argument("--dry-run", action="store_true", help="Simulera utan att skriva till Odoo")
    parser.add_argument("--file", default=str(DEFAULT_JSON), help="Sökväg till JSON-fil")
    args = parser.parse_args()

    json_path = Path(args.file)
    if not json_path.exists():
        print(f"Filen hittades inte: {json_path}")
        sys.exit(1)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    tracks = data.get("tracks", [])
    print(f"Läser {len(tracks)} låtar från {json_path.name}")

    uid, models = (None, None) if args.dry_run else connect()
    if args.dry_run:
        print("[DRY RUN — inga ändringar skrivs]")

    genre_cache: dict = {}
    counts = {"created": 0, "updated": 0}

    for track in tracks:
        result = upsert_song(models, uid, track, genre_cache, args.dry_run)
        if result in counts:
            counts[result] += 1

    print(f"\nKlart: {counts['created']} skapade, {counts['updated']} uppdaterade")


if __name__ == "__main__":
    main()
