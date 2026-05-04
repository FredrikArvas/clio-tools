"""
clio-vigil — archiver.py
=========================
Laddar ned och arkiverar hela källarkiv lokalt.

Sprint C: fristående arkivering utanför bevakningspipelinen.
  - Flagga archive: true per källa i YAML aktiverar arkivering
  - YouTube: laddar ned hela kanalen via yt-dlp (undviker dubbletter via .archive-fil)
  - RSS/podcast: laddar ned alla enclosure-URLs direkt
  - Lagring: ARCHIVE_DIR/{source_slug}/ (default /home/clioadmin/clio-archive/)
  - Spårar nedladdade filer i SQLite (source_archives) och sätter archive_downloaded=1

Körning:
  python archiver.py --run                    # Arkivera alla källor med archive:true
  python archiver.py --source "The Black Vault"  # Arkivera en specifik källa
  python archiver.py --list                   # Lista arkiverade källor och storlek
  python archiver.py --stats                  # Visa statistik

Miljövariabel:
  VIGIL_ARCHIVE_DIR=/path/to/archive   (default: /home/clioadmin/clio-archive)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from orchestrator import init_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

_HERE       = Path(__file__).parent
CONFIG_DIR  = _HERE / "config"

# Arkivkatalog — utanför Dropbox, konfigurerbar via miljövariabel
ARCHIVE_DIR = Path(os.getenv("VIGIL_ARCHIVE_DIR", "/home/clioadmin/clio-archive"))

# yt-dlp DownloadArchive-fil per källa (håller koll på nedladdade videos)
def _ytdlp_archive_file(source_slug: str) -> Path:
    return ARCHIVE_DIR / source_slug / ".ytdlp_archive.txt"


def _make_slug(text: str) -> str:
    """Normaliserar text till fil-säkert slug."""
    import re
    text = text.lower()
    text = text.replace("å", "a").replace("ä", "a").replace("ö", "o")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:40]


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _load_all_configs() -> list[dict]:
    """Laddar alla domänkonfigurationer."""
    configs = []
    for yaml_file in CONFIG_DIR.glob("*.yaml"):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                configs.append(yaml.safe_load(f))
        except Exception as e:
            logger.warning(f"Kunde inte läsa {yaml_file}: {e}")
    return configs


def _get_archivable_sources(configs: list[dict],
                             filter_name: Optional[str] = None) -> list[dict]:
    """
    Returnerar alla källor med archive: true.
    filter_name: begränsa till en specifik källa.
    """
    archivable = []
    for cfg in configs:
        domain = cfg.get("domain_id", "")
        for src in cfg.get("sources", {}).get("rss", []):
            if src.get("archive") and (not filter_name or filter_name.lower() in src.get("name", "").lower()):
                archivable.append({**src, "domain": domain, "source_type": "rss"})
        for src in cfg.get("sources", {}).get("youtube_channels", []):
            if src.get("archive") and (not filter_name or filter_name.lower() in src.get("name", src.get("channel_id", "")).lower()):
                archivable.append({**src, "domain": domain, "source_type": "youtube"})
    return archivable


def _record_archive(conn, source_name: str, url: str,
                    local_path: Optional[str], file_size_mb: Optional[float],
                    status: str = "ok") -> None:
    """Registrerar en nedladdning i source_archives-tabellen och uppdaterar vigil_items."""
    # Spara i source_archives
    conn.execute(
        """INSERT INTO source_archives (source_name, url, local_path, file_size_mb, archive_status)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET
             local_path     = excluded.local_path,
             file_size_mb   = excluded.file_size_mb,
             archive_status = excluded.archive_status,
             archived_at    = datetime('now')""",
        (source_name, url, local_path, file_size_mb, status)
    )
    # Uppdatera vigil_items om URL finns
    if local_path and status == "ok":
        conn.execute(
            """UPDATE vigil_items
               SET archive_downloaded = 1, archive_path = ?
               WHERE url = ?""",
            (local_path, url)
        )
    conn.commit()


# ---------------------------------------------------------------------------
# YouTube-arkivering
# ---------------------------------------------------------------------------

def archive_youtube_channel(conn, source: dict, dry_run: bool = False) -> dict:
    """
    Laddar ned hela YouTube-kanalen till ARCHIVE_DIR/{slug}/.
    Använder yt-dlp download-archive för att hoppa redan nedladdade videos.
    Returnerar räknare: {downloaded, skipped, failed}.
    """
    try:
        import yt_dlp
    except ImportError:
        raise ImportError("yt-dlp saknas — kör: pip install yt-dlp")

    channel_id   = source.get("channel_id", "")
    name         = source.get("name", channel_id)
    slug         = _make_slug(name)
    dest_dir     = ARCHIVE_DIR / slug
    archive_file = _ytdlp_archive_file(slug)

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    # Bygg kanal-URL
    if channel_id.startswith("@") or channel_id.startswith("UC"):
        if channel_id.startswith("UC"):
            channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
        else:
            channel_url = f"https://www.youtube.com/{channel_id}/videos"
    else:
        channel_url = f"https://www.youtube.com/@{channel_id}/videos"

    logger.info(f"YouTube-arkiv: {name} → {dest_dir}")

    counts = {"downloaded": 0, "skipped": 0, "failed": 0}

    if dry_run:
        logger.info(f"[dry-run] Skulle ladda ned: {channel_url} → {dest_dir}")
        return counts

    # Hämta metadata för alla videos i kanalen (för att registrera i SQLite)
    meta_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }
    video_urls = []
    try:
        with yt_dlp.YoutubeDL(meta_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
        if info and "entries" in info:
            for entry in (info["entries"] or []):
                if entry and entry.get("id"):
                    video_urls.append(f"https://www.youtube.com/watch?v={entry['id']}")
    except Exception as e:
        logger.warning(f"Metadatahämtning misslyckades för {name}: {e}")

    # Ladda ned med yt-dlp
    ydl_opts = {
        "quiet": False,
        "no_warnings": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(dest_dir / "%(upload_date)s_%(title)s_%(id)s.%(ext)s"),
        "download_archive": str(archive_file),
        "ignoreerrors": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "5",
        }],
    }

    class _Counter:
        """Räknar nedladdningar via yt-dlp progress-hook."""
        downloaded = 0
        skipped    = 0

    ctr = _Counter()

    def _progress_hook(d):
        if d["status"] == "finished":
            ctr.downloaded += 1
        elif d["status"] == "already_downloaded":
            ctr.skipped += 1

    ydl_opts["progress_hooks"] = [_progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([channel_url])
        counts["downloaded"] = ctr.downloaded
        counts["skipped"]    = ctr.skipped
    except Exception as e:
        logger.error(f"yt-dlp misslyckades för {name}: {e}")
        counts["failed"] += 1

    # Registrera nedladdade filer i SQLite
    for vurl in video_urls:
        mp3_candidates = list(dest_dir.glob("*.mp3"))
        local_path = str(mp3_candidates[-1]) if mp3_candidates else None
        _record_archive(conn, name, vurl, local_path=None, file_size_mb=None)

    logger.info(
        f"YouTube-arkiv klar [{name}]: "
        f"{counts['downloaded']} nya, {counts['skipped']} redan klara, "
        f"{counts['failed']} fel"
    )
    return counts


# ---------------------------------------------------------------------------
# RSS/Podcast-arkivering
# ---------------------------------------------------------------------------

def archive_rss_feed(conn, source: dict, dry_run: bool = False) -> dict:
    """
    Laddar ned alla enclosure-URLs från ett RSS-flöde.
    Hoppar över filer som redan finns i ARCHIVE_DIR/{slug}/.
    Returnerar räknare: {downloaded, skipped, failed}.
    """
    try:
        import feedparser
        import requests
    except ImportError as e:
        raise ImportError(f"Saknat beroende: {e} — pip install feedparser requests")

    url     = source.get("url", "")
    name    = source.get("name", url)
    slug    = _make_slug(name)
    dest_dir = ARCHIVE_DIR / slug

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"RSS-arkiv: {name} → {dest_dir}")

    counts = {"downloaded": 0, "skipped": 0, "failed": 0}

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        logger.error(f"Feedparser-fel för {name}: {e}")
        counts["failed"] += 1
        return counts

    for entry in feed.entries:
        # Hitta enclosure-URL (ljudfil)
        audio_url = None
        if hasattr(entry, "enclosures") and entry.enclosures:
            enc = entry.enclosures[0]
            audio_url = enc.get("href") or enc.get("url")
        if not audio_url:
            for link in getattr(entry, "links", []):
                if link.get("rel") == "enclosure":
                    audio_url = link.get("href")
                    break
        if not audio_url:
            continue   # Ingen audio-fil — hoppa

        # Bygg filnamn från URL
        filename = audio_url.rstrip("/").split("/")[-1].split("?")[0]
        if not filename or "." not in filename:
            filename = f"{_make_slug(entry.get('title', 'okand'))}.mp3"
        dest_file = dest_dir / filename

        # Kolla om vi redan har filen
        if dest_file.exists():
            _record_archive(conn, name, getattr(entry, "link", audio_url),
                            str(dest_file), dest_file.stat().st_size / (1024*1024))
            counts["skipped"] += 1
            continue

        if dry_run:
            logger.info(f"[dry-run] Skulle ladda ned: {audio_url} → {dest_file}")
            counts["downloaded"] += 1
            continue

        # Ladda ned
        try:
            logger.info(f"Laddar ned: {filename}")
            with requests.get(audio_url, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(dest_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)

            size_mb = dest_file.stat().st_size / (1024 * 1024)
            _record_archive(conn, name, getattr(entry, "link", audio_url),
                            str(dest_file), size_mb)
            counts["downloaded"] += 1
            logger.info(f"  ✓ {filename} ({size_mb:.1f} MB)")

        except Exception as e:
            logger.error(f"  ✗ Nedladdningsfel {filename}: {e}")
            _record_archive(conn, name, getattr(entry, "link", audio_url),
                            None, None, status="error")
            counts["failed"] += 1

    logger.info(
        f"RSS-arkiv klar [{name}]: "
        f"{counts['downloaded']} nya, {counts['skipped']} redan klara, "
        f"{counts['failed']} fel"
    )
    return counts


# ---------------------------------------------------------------------------
# Huvud-funktion
# ---------------------------------------------------------------------------

def run_archive(conn, filter_name: Optional[str] = None,
                dry_run: bool = False) -> dict:
    """
    Arkiverar alla källor med archive: true i YAML-konfigurationen.
    filter_name: begränsa till källa vars namn matchar (case-insensitive).
    Returnerar aggregerade räknare.
    """
    configs   = _load_all_configs()
    sources   = _get_archivable_sources(configs, filter_name)

    if not sources:
        if filter_name:
            logger.warning(f"Ingen arkiverbar källa hittades för: {filter_name}")
        else:
            logger.info("Inga källor med 'archive: true' i YAML. Lägg till flaggan för att aktivera.")
        return {"downloaded": 0, "skipped": 0, "failed": 0, "sources": 0}

    totals = {"downloaded": 0, "skipped": 0, "failed": 0, "sources": len(sources)}

    for src in sources:
        src_type = src.get("source_type", "rss")
        try:
            if src_type == "youtube":
                counts = archive_youtube_channel(conn, src, dry_run=dry_run)
            else:
                counts = archive_rss_feed(conn, src, dry_run=dry_run)
            for k in ("downloaded", "skipped", "failed"):
                totals[k] += counts.get(k, 0)
        except Exception as e:
            logger.error(f"Arkiveringsfel [{src.get('name')}]: {e}", exc_info=True)
            totals["failed"] += 1

    logger.info(
        f"Arkivering klar: {totals['sources']} källor, "
        f"{totals['downloaded']} nya, {totals['skipped']} redan klara, "
        f"{totals['failed']} fel"
    )
    return totals


def list_archives(conn) -> None:
    """Listar arkiverade källor med storlek och antal episoder."""
    rows = conn.execute(
        """SELECT source_name,
                  COUNT(*) as episodes,
                  ROUND(SUM(file_size_mb), 1) as total_mb,
                  MAX(archived_at) as last_archived
           FROM source_archives
           WHERE archive_status = 'ok'
           GROUP BY source_name
           ORDER BY total_mb DESC"""
    ).fetchall()

    if not rows:
        print("Inga arkiverade källor ännu.")
        return

    print(f"\n{'Källa':<35} {'Avsnitt':>8} {'Storlek':>10} {'Senast':>12}")
    print("─" * 70)
    total_mb = 0
    for r in rows:
        mb   = r["total_mb"] or 0
        date = (r["last_archived"] or "")[:10]
        print(f"  {r['source_name'][:33]:<33} {r['episodes']:>8} {mb:>8.1f} MB {date:>12}")
        total_mb += mb
    print("─" * 70)
    print(f"  {'TOTALT':<33} {sum(r['episodes'] for r in rows):>8} {total_mb:>8.1f} MB")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="clio-vigil archiver — laddar ned hela källarkiv"
    )
    parser.add_argument("--run",      action="store_true", help="Arkivera alla källor med archive:true")
    parser.add_argument("--source",   type=str,            help="Arkivera en specifik källa (namnmatchning)")
    parser.add_argument("--list",     action="store_true", help="Lista arkiverade filer och storlek")
    parser.add_argument("--dry-run",  action="store_true", help="Simulera utan faktisk nedladdning")
    args = parser.parse_args()

    conn = init_db()

    if args.list:
        list_archives(conn)

    elif args.run or args.source:
        totals = run_archive(conn, filter_name=args.source, dry_run=args.dry_run)
        print(
            f"\n✓ Arkivering klar: {totals['sources']} källor, "
            f"{totals['downloaded']} nedladdade, "
            f"{totals['skipped']} redan klara, "
            f"{totals['failed']} misslyckade"
        )
        if args.dry_run:
            print("  (dry-run — inga filer nedladdades)")
    else:
        parser.print_help()

    conn.close()


if __name__ == "__main__":
    _main()
