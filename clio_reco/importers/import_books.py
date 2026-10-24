"""Import av böcker från books_about_death.json → clio.reco.item (item_type=book).

Upsert-nyckel: isbn (hoppar över poster utan isbn om de redan finns med samma title+author).
Kör: python import_books.py [--dry-run] [--file /annan/sökväg.json]
"""
import argparse
import json
import sys
from pathlib import Path

from odoo_client import ODOO_DB, ODOO_PASSWORD, connect, ensure_genre

DEFAULT_JSON = Path(__file__).parent.parent.parent.parent / (
    "Dropbox/projekt/Clio-projekt/Clio_Reco/books_about_death.json"
)


def build_description(book: dict) -> str:
    parts = []
    if book.get("theme"):
        parts.append(f"<p><b>Tema:</b> {book['theme']}</p>")
    if book.get("description"):
        parts.append(f"<p>{book['description']}</p>")
    if book.get("relevance"):
        parts.append(f"<p><i>{book['relevance']}</i></p>")
    return "".join(parts)


def upsert_book(models, uid, book: dict, genre_cache: dict, dry_run: bool) -> str:
    isbn = book.get("isbn", "").strip()
    title = book["title"].strip()
    author = book.get("author", "").strip()

    # Hitta befintlig post
    domain = [["item_type", "=", "book"]]
    if isbn:
        domain.append(["isbn", "=", isbn])
    else:
        domain += [["name", "=", title], ["author", "=", author]]

    existing = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "clio.reco.item", "search", [domain])

    category = book.get("category", "Övrigt").strip()
    if category not in genre_cache:
        genre_cache[category] = ensure_genre(models, uid, category) if not dry_run else -1
    genre_id = genre_cache[category]

    vals = {
        "name": title,
        "item_type": "book",
        "author": author,
        "year": book.get("year") or False,
        "isbn": isbn or False,
        "description": build_description(book),
        "genre_ids": [(4, genre_id)] if genre_id > 0 else [],
        "is_published": True,
    }

    if dry_run:
        action = "UPDATE" if existing else "CREATE"
        print(f"  [{action}] {title} ({isbn or 'inget isbn'})")
        return action.lower()

    if existing:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "clio.reco.item", "write", [existing, vals])
        return "updated"
    else:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "clio.reco.item", "create", [vals])
        return "created"


def main():
    parser = argparse.ArgumentParser(description="Importera böcker till clio_reco")
    parser.add_argument("--dry-run", action="store_true", help="Simulera utan att skriva till Odoo")
    parser.add_argument("--file", default=str(DEFAULT_JSON), help="Sökväg till JSON-fil")
    args = parser.parse_args()

    json_path = Path(args.file)
    if not json_path.exists():
        print(f"Filen hittades inte: {json_path}")
        sys.exit(1)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    books = data.get("books", [])
    print(f"Läser {len(books)} böcker från {json_path.name}")

    uid, models = (None, None) if args.dry_run else connect()
    if args.dry_run:
        print("[DRY RUN — inga ändringar skrivs]")

    genre_cache: dict = {}
    counts = {"created": 0, "updated": 0}

    for book in books:
        result = upsert_book(models, uid, book, genre_cache, args.dry_run)
        if result in counts:
            counts[result] += 1

    print(f"\nKlart: {counts['created']} skapade, {counts['updated']} uppdaterade")


if __name__ == "__main__":
    main()
