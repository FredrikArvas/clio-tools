"""
clio-vigil — collectors/youtube_collector.py
=============================================
Hämtar metadata från YouTube-kanaler via yt-dlp.
Laddar INTE ned video/audio här — det sker i transcriber.py efter filtrering.

Designbeslut:
  - yt-dlp extract_info med download=False → bara metadata
  - Kanalbevakning: hämtar senaste N videor per kanal
  - duration_seconds från metadata → används i prioritetstal
  - Preemptiv kö hanteras i orchestrator, inte här
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# Antal senaste videor att kontrollera per kanal
DEFAULT_MAX_VIDEOS = 10


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def _parse_upload_date(date_str: Optional[str]) -> Optional[str]:
    """Konverterar yt-dlp YYYYMMDD till ISO 8601."""
    if not date_str or len(date_str) != 8:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


def _build_channel_url(channel_id: str) -> str:
    """Bygger URL för kanalens senaste videor."""
    if channel_id.startswith("UC"):
        return f"https://www.youtube.com/channel/{channel_id}/videos"
    if channel_id.startswith("@"):
        return f"https://www.youtube.com/{channel_id}/videos"
    return f"https://www.youtube.com/@{channel_id}/videos"


# ---------------------------------------------------------------------------
# Huvud-collector
# ---------------------------------------------------------------------------

def collect_youtube(conn, domain_config: dict,
                    max_videos: int = DEFAULT_MAX_VIDEOS) -> dict:
    """
    Hämtar metadata för senaste videor från konfigurerade YouTube-kanaler.
    Returnerar räknare: {discovered: N, skipped: N, errors: N}
    """
    if yt_dlp is None:
        raise ImportError("yt-dlp saknas — kör: pip install yt-dlp")

    from orchestrator import upsert_item

    domain_id = domain_config["domain_id"]
    channels = domain_config.get("sources", {}).get("youtube_channels", [])
    counts = {"discovered": 0, "skipped": 0, "errors": 0}

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,          # Bara metadata, ingen nedladdning
        "playlist_items": f"1:{max_videos}",
        "ignoreerrors": True,
    }

    for channel in channels:
        channel_id = channel["channel_id"]
        name = channel.get("name", channel_id)
        maturity = channel.get("maturity", "tidig")
        weight = channel.get("weight", 1.0)
        channel_url = _build_channel_url(channel_id)

        logger.info(f"YouTube: hämtar {name} ({channel_url})")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

            if not info or "entries" not in info:
                logger.warning(f"Inga videor hittades för {name}")
                counts["errors"] += 1
                continue

            for entry in info["entries"]:
                if not entry:
                    continue

                video_id = entry.get("id")
                if not video_id:
                    continue

                video_url = f"https://www.youtube.com/watch?v={video_id}"
                title = entry.get("title", "")
                description = entry.get("description", "") or ""
                duration = entry.get("duration")  # sekunder eller None
                upload_date = _parse_upload_date(entry.get("upload_date"))

                # Beskrivning för filter: titel + första 500 tecken av beskrivning
                filter_text = f"{title} {description[:500]}"

                item_id = upsert_item(
                    conn,
                    url=video_url,
                    domain=domain_id,
                    source_type="youtube",
                    source_name=name,
                    source_maturity=maturity,
                    source_weight=weight,
                    title=title,
                    description=filter_text,
                    published_at=upload_date,
                    duration_seconds=duration,
                    raw_metadata=json.dumps({
                        "channel_id": channel_id,
                        "video_id": video_id,
                        "channel_url": channel_url,
                        "view_count": entry.get("view_count"),
                    })
                )

                if item_id:
                    counts["discovered"] += 1
                else:
                    counts["skipped"] += 1

        except Exception as e:
            logger.error(f"Fel vid hämtning av YouTube-kanal {name}: {e}")
            counts["errors"] += 1

    logger.info(
        f"YouTube-insamling klar [{domain_id}]: "
        f"{counts['discovered']} nya, {counts['skipped']} kända, {counts['errors']} fel"
    )
    return counts
