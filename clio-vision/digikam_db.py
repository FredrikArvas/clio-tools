"""
digikam_db.py
DigiKam-integration för clio-vision.

Läser DigiKam4.db och visar:
- Statistik över taggade bilder och personer
- Lista över album att välja för clio-vision-analys

Usage:
    python digikam_db.py
"""

import sys
import io
import sqlite3
import subprocess
from pathlib import Path

# Säkerställ UTF-8 på Windows-konsol
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

DIGIKAM_RC = Path.home() / "AppData" / "Local" / "digikamrc"

DB_SEARCH_PATHS = [
    Path.home() / "Pictures" / "digikam4.db",
    Path.home() / "Documents" / "digikam4.db",
    Path("D:/Pictures/digikam4.db"),
]

GRN = "\033[92m"
YEL = "\033[93m"
GRY = "\033[90m"
BLD = "\033[1m"
NRM = "\033[0m"
CYN = "\033[96m"

# ── DB-sökning ────────────────────────────────────────────────────────────────

def find_db() -> Path | None:
    """Hitta digikam4.db via digikamrc eller vanliga platser."""
    # 1. Läs digikamrc
    if DIGIKAM_RC.exists():
        for line in DIGIKAM_RC.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Database Name="):
                folder = line.split("=", 1)[1].strip()
                candidate = Path(folder.replace("/", "\\")) / "digikam4.db"
                if candidate.exists():
                    return candidate

    # 2. Fallback: kända platser
    for p in DB_SEARCH_PATHS:
        if p.exists():
            return p

    return None


# ── Databasfrågor ─────────────────────────────────────────────────────────────

def get_stats(conn: sqlite3.Connection) -> dict:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM Images")
    total_images = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT imageid) FROM ImageTags")
    tagged_images = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(*) FROM Tags t
        JOIN TagProperties tp ON t.id = tp.tagid
        WHERE tp.property = 'person'
    """)
    total_persons = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM Albums WHERE albumRoot > 0")
    total_albums = c.fetchone()[0]

    return {
        "total_images": total_images,
        "tagged_images": tagged_images,
        "total_persons": total_persons,
        "total_albums": total_albums,
    }


def get_top_persons(conn: sqlite3.Connection, limit: int = 15) -> list[tuple]:
    """Returnerar [(person_name, count), ...] sorterat fallande."""
    c = conn.cursor()
    c.execute("""
        SELECT tp.value, COUNT(DISTINCT it.imageid) AS cnt
        FROM TagProperties tp
        JOIN Tags t ON tp.tagid = t.id
        JOIN ImageTags it ON t.id = it.tagid
        WHERE tp.property = 'person'
        GROUP BY tp.value
        ORDER BY cnt DESC
        LIMIT ?
    """, (limit,))
    return c.fetchall()


def get_albums(conn: sqlite3.Connection) -> list[dict]:
    """Returnerar alla album med antal bilder och AlbumRoot-sökväg."""
    c = conn.cursor()
    c.execute("""
        SELECT
            a.id,
            a.albumRoot,
            a.relativePath,
            COUNT(i.id) AS img_count,
            ar.specificPath
        FROM Albums a
        LEFT JOIN Images i ON i.album = a.id
        LEFT JOIN AlbumRoots ar ON a.albumRoot = ar.id
        WHERE a.albumRoot > 0
        GROUP BY a.id
        HAVING img_count > 0
        ORDER BY a.relativePath
    """)
    rows = c.fetchall()
    albums = []
    for row in rows:
        album_id, root_id, rel_path, img_count, specific_path = row
        # Bygg absolut sökväg
        if specific_path:
            # specificPath är /staff/Dropbox → mappa till Windows-sökväg
            # Försök tolka som relativ till kända rötter
            abs_path = _resolve_path(specific_path, rel_path)
        else:
            abs_path = None
        albums.append({
            "id": album_id,
            "rel": rel_path,
            "count": img_count,
            "abs": abs_path,
        })
    return albums


def _resolve_path(specific_path: str, rel_path: str) -> str | None:
    """Försök mappa DigiKam-sökväg till Windows-sökväg."""
    # specific_path kan vara t.ex. "/staff/Dropbox" → C:\Users\fredr\Documents\Dropbox
    mapping = {
        "/staff/Dropbox": str(Path.home() / "Documents" / "Dropbox"),
    }
    for prefix, win_root in mapping.items():
        if specific_path.startswith(prefix):
            remainder = specific_path[len(prefix):]
            full = win_root + remainder.replace("/", "\\") + rel_path.replace("/", "\\")
            return full

    # Försök direkt
    candidate = (specific_path + rel_path).replace("/", "\\")
    if Path(candidate).exists():
        return candidate

    return specific_path + rel_path  # returnera rå sökväg som fallback


# ── Utskrift ──────────────────────────────────────────────────────────────────

def print_stats(stats: dict, db_path: Path):
    print(f"\n{BLD}  DigiKam-databas{NRM}")
    print(f"  {GRY}{db_path}{NRM}")
    print(f"  {'─' * 50}")
    print(f"  Bilder totalt:      {GRN}{stats['total_images']:>8,}{NRM}")
    print(f"  Bilder med taggar:  {GRN}{stats['tagged_images']:>8,}{NRM}")
    print(f"  Kända personer:     {GRN}{stats['total_persons']:>8,}{NRM}")
    print(f"  Album:              {GRN}{stats['total_albums']:>8,}{NRM}")


def print_top_persons(persons: list[tuple]):
    print(f"\n{BLD}  Mest förekommande personer{NRM}")
    print(f"  {'─' * 40}")
    for i, (name, cnt) in enumerate(persons, 1):
        bar = "█" * min(cnt // 10, 30)
        print(f"  {i:2}. {name:<25} {GRN}{cnt:>5}{NRM}  {GRY}{bar}{NRM}")


def print_albums(albums: list[dict], page: int = 0, page_size: int = 20):
    start = page * page_size
    subset = albums[start:start + page_size]
    total_pages = (len(albums) - 1) // page_size + 1

    print(f"\n{BLD}  Album  (sida {page+1}/{total_pages}){NRM}")
    print(f"  {'─' * 60}")
    for i, alb in enumerate(subset, start + 1):
        abs_str = f"  {GRY}{alb['abs']}{NRM}" if alb["abs"] else ""
        print(f"  {YEL}{i:4}.{NRM} {alb['rel']:<40} {GRN}{alb['count']:>5} bilder{NRM}{abs_str}")


# ── Huvud-meny ────────────────────────────────────────────────────────────────

def main():
    db_path = find_db()
    if not db_path:
        print(f"\n{YEL}DigiKam-databas hittades inte.{NRM}")
        print("Sökte i:")
        for p in DB_SEARCH_PATHS:
            print(f"  {p}")
        print(f"\nKontrollera att DigiKam är installerat och att databasen finns.")
        input("\nTryck Enter för att fortsätta...")
        return

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    try:
        stats = get_stats(conn)
        persons = get_top_persons(conn)
        albums = get_albums(conn)

        album_page = 0

        while True:
            print("\033[2J\033[H", end="")  # clear
            print_stats(stats, db_path)
            print_top_persons(persons)
            print_albums(albums, album_page)

            print(f"\n  {YEL}n{NRM}  Nästa albumsida  "
                  f"  {YEL}p{NRM}  Föregående  "
                  f"  {YEL}v{NRM}  Välj album → clio-vision  "
                  f"  {YEL}b{NRM}  Tillbaka\n")
            choice = input("  Val: ").strip().lower()

            if choice == "b":
                break
            elif choice == "n":
                if (album_page + 1) * 20 < len(albums):
                    album_page += 1
            elif choice == "p":
                if album_page > 0:
                    album_page -= 1
            elif choice == "v":
                nr = input("  Albumnummer: ").strip()
                if nr.isdigit():
                    idx = int(nr) - 1
                    if 0 <= idx < len(albums):
                        alb = albums[idx]
                        folder = alb["abs"] or alb["rel"]
                        print(f"\n  {GRN}Startar clio-vision på:{NRM} {folder}")
                        vision_script = Path(__file__).parent / "clio_vision.py"
                        if vision_script.exists() and Path(folder).is_dir():
                            subprocess.run([sys.executable, str(vision_script), folder])
                        elif not Path(folder).is_dir():
                            print(f"\n  {YEL}Mappen finns inte lokalt (kanske online-only?){NRM}")
                            input("  Tryck Enter...")
                        else:
                            print(f"\n  {YEL}clio_vision.py hittades inte{NRM}")
                            input("  Tryck Enter...")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
