"""
clio-vigil — spotify_handler.py
=================================
Hämtar Spotifys egna transkript för podcavsnitt utan att ladda ner audio.

Flöde:
  1. Extrahera episod-ID (22 tecken base62) från open.spotify.com/episode/{id}-URL
  2. Hämta cipher-bytes från community-repo → konstruera TOTP-nyckel
  3. Hämta serverns klocktid för säkert TOTP-fönster
  4. Byt ut sp_dc-cookie mot kort bearer-token via open.spotify.com/api/token
  5. Anropa spclient.wg.spotify.com/transcript-read-along/v2/episode/{id}
  6. Normalisera Spotifys section-format till vigil-format: [{start, end, text}]
  7. Spara JSON + TXT → transition(conn, item_id, "transcribed")

Kräver:
  SPOTIFY_SP_DC i .env  (sessionscookie från inloggad Spotify-webbläsare —
                          DevTools → Application → Cookies → sp_dc på open.spotify.com)

Inga extra beroenden utöver requests (redan installerat).
TOTP är implementerat med stdlib hmac/hashlib/struct.

Begränsningar:
  - Fungerar bara för episoder som Spotify har transkriberat (ej alla avsnitt).
    Engelska poddar har bäst täckning; svenska poddar varierar.
  - Inofficiellt API — Spotify kan ändra endpoints utan förvarning.
  - sp_dc-cookien är personlig, roteras ej automatiskt och kan gå ut.
  - cipher_bytes-formatet kan ändras om Spotify byter JS-bundle.

Alternativ (ej implementerat här):
  Playwright på servern: browser.new_page() + context.add_cookies([sp_dc-cookie])
  → navigera till open.spotify.com/episode/{id} → läs ut transkript via DOM.
  Robust mot API-ändringar men 10× långsammare. Använd om API-vägen bryts.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

from orchestrator import transition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths och konstanter
# ---------------------------------------------------------------------------

DATA_DIR        = Path(__file__).parent / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
_SECRETS_CACHE  = DATA_DIR / "spotify_secrets.json"

# community-underhållen extraktion av Spotifys interna cipher-bytes
# Formatet: [{"version": N, "secret": [int, ...]}, ...]  — högsta version används
# Källa: xyloflake/spot-secrets-go (refererat av trustos/spotify-transcript)
_SECRETS_URL = "https://raw.githubusercontent.com/xyloflake/spot-secrets-go/main/secrets/secretBytes.json"

# Spotifys endpoints
_TOKEN_URL      = "https://open.spotify.com/api/token"
_TRANSCRIPT_URL = "https://spclient.wg.spotify.com/transcript-read-along/v2/episode/{episode_id}"

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# In-process token-cache (uppdateras automatiskt när token löper ut)
_token_cache: dict = {}

# Ladda .env
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent / ".env", override=True)


# ---------------------------------------------------------------------------
# URL-hantering
# ---------------------------------------------------------------------------

def is_spotify_episode(url: str) -> bool:
    """Returnerar True om URL:en är ett open.spotify.com-avsnitt."""
    return bool(re.search(r"open\.spotify\.com/episode/", url))


def _episode_id(url: str) -> Optional[str]:
    """Extraherar 22-teckens base62-ID från open.spotify.com/episode/{id}."""
    m = re.search(r"open\.spotify\.com/episode/([A-Za-z0-9]{22})", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# TOTP — stdlib-implementation (inga extra beroenden)
# ---------------------------------------------------------------------------

def _totp(key_bytes: bytes, t: int, digits: int = 6, interval: int = 30) -> str:
    """
    RFC 6238 TOTP med HMAC-SHA1.
    t = Unix-tid i sekunder (heltal). Returnerar nollpaddat OTP-strängen.
    """
    counter = struct.pack(">Q", t // interval)
    h = hmac.new(key_bytes, counter, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def _cipher_to_key(cipher_bytes: list[int]) -> bytes:
    """
    Omvandlar Spotifys cipher-bytes till TOTP-nyckelmaterial.

    Algoritm (trustos/spotify-transcript):
      1. XOR varje byte med ((i % 33) + 9)
      2. Konkatenera de transformerade talen som decimalsträngar
      3. hex-koda den resulterande strängen
      4. Konvertera hex-strängen till bytes

    Resultatet är de råa HMAC-nyckelbyten.
    """
    transformed = [b ^ ((i % 33) + 9) for i, b in enumerate(cipher_bytes)]
    joined      = "".join(str(n) for n in transformed)
    hex_str     = joined.encode().hex()
    return bytes.fromhex(hex_str)


def _load_cipher() -> tuple[bytes, int]:
    """
    Hämtar Spotifys cipher-bytes och returnerar (key_bytes, version).
    Cachas i data/spotify_secrets.json, uppdateras var 24:e timme.
    Kastar RuntimeError om varken nätverk eller cache är tillgänglig.

    secretBytes.json-formatet (xyloflake/spot-secrets-go):
      [{"version": N, "secret": [int, ...]}, ...]
    Högsta version används. secret-bytearna transformeras av _cipher_to_key().
    """
    # Använd cache om den är färsk
    if _SECRETS_CACHE.exists():
        try:
            cached = json.loads(_SECRETS_CACHE.read_text(encoding="utf-8"))
            age_h  = (time.time() - cached.get("fetched_at", 0)) / 3600
            if age_h < 24 and cached.get("key_hex") and cached.get("version"):
                return bytes.fromhex(cached["key_hex"]), int(cached["version"])
        except Exception:
            pass  # Felaktig cache — hämta ny

    logger.info("[spotify] Hämtar cipher-secrets från xyloflake/spot-secrets-go")
    try:
        resp = requests.get(_SECRETS_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        # Försök med eventuell föråldrad cache
        if _SECRETS_CACHE.exists():
            try:
                cached = json.loads(_SECRETS_CACHE.read_text(encoding="utf-8"))
                if cached.get("key_hex") and cached.get("version"):
                    logger.warning("[spotify] Nätverksfel — använder gammal cache: %s", e)
                    return bytes.fromhex(cached["key_hex"]), int(cached["version"])
            except Exception:
                pass
        raise RuntimeError(f"Kan inte hämta cipher-secrets: {e}") from e

    # Format: lista av {"version": N, "secret": [int, ...]}
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"Oväntat format från secrets-URL: {type(data)}")

    try:
        latest       = max(data, key=lambda x: int(x["version"]))
        version      = int(latest["version"])
        cipher_bytes = latest["secret"]
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError(f"Kan inte parsa secretBytes.json: {e}") from e

    if not isinstance(cipher_bytes, list) or not cipher_bytes:
        raise RuntimeError(f"cipher_bytes är tom eller fel typ: {type(cipher_bytes)}")

    key_bytes = _cipher_to_key(cipher_bytes)

    # Spara cache
    _SECRETS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _SECRETS_CACHE.write_text(
        json.dumps(
            {"fetched_at": time.time(), "version": version, "key_hex": key_bytes.hex()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info("[spotify] Cipher version %d cachad", version)
    return key_bytes, version


# ---------------------------------------------------------------------------
# Serverts klocka — minskar risken för TOTP-fönstermissar
# ---------------------------------------------------------------------------

def _server_time() -> int:
    """
    Hämtar Spotifys servertid som Unix-sekunder.
    Spotify-API:ets Date-header används om möjligt, annars lokal klocka.
    """
    try:
        resp = requests.head("https://open.spotify.com", timeout=5)
        date_hdr = resp.headers.get("Date")
        if date_hdr:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_hdr)
            return int(dt.timestamp())
    except Exception as e:
        logger.debug("[spotify] Servertid ej tillgänglig (%s) — använder lokal tid", e)
    return int(time.time())


# ---------------------------------------------------------------------------
# Token-utbyte
# ---------------------------------------------------------------------------

def _get_token(sp_dc: str) -> str:
    """
    Byter sp_dc-cookie mot Spotifys bearer-token via /api/token.
    Cachar token i minnet tills den löper ut (vanligtvis ~1 timme).
    Kastar RuntimeError vid misslyckande.
    """
    now    = time.time()
    cached = _token_cache.get("token")
    expiry = _token_cache.get("expires_at", 0)
    if cached and now < expiry - 60:
        return cached

    key_bytes, totp_ver = _load_cipher()
    srv_time = _server_time()
    otp      = _totp(key_bytes, srv_time)

    params = {
        "reason":      "transport",
        "productType": "web-player",
        "totp":        otp,
        "totpVer":     totp_ver,
        "totpKey":     totp_ver,   # äldre versioner av endpointen vill ha detta
    }
    headers = {
        "User-Agent": _UA,
        "Cookie":     f"sp_dc={sp_dc}",
        "Accept":     "application/json",
    }

    try:
        resp = requests.get(_TOKEN_URL, params=params, headers=headers, timeout=15)
    except Exception as e:
        raise RuntimeError(f"Nätverksfel mot token-endpoint: {e}") from e

    if resp.status_code == 401:
        raise RuntimeError(
            "401 Unauthorized — sp_dc-cookien är ogiltig eller utgången. "
            "Hämta en ny från DevTools → Application → Cookies på open.spotify.com."
        )
    if not resp.ok:
        raise RuntimeError(
            f"Token-endpoint svarade {resp.status_code}: {resp.text[:200]}"
        )

    payload = resp.json()
    token   = payload.get("accessToken")
    if not token:
        raise RuntimeError(f"Inget accessToken i svar (nycklar: {list(payload.keys())})")

    expires_ms = payload.get("accessTokenExpirationTimestampMs", 0)
    expires_at = (expires_ms / 1000) if expires_ms else (now + 3600)

    _token_cache["token"]      = token
    _token_cache["expires_at"] = expires_at
    logger.debug(
        "[spotify] Token hämtad, giltig till %s",
        datetime.fromtimestamp(expires_at).strftime("%H:%M:%S"),
    )
    return token


# ---------------------------------------------------------------------------
# Transkript-hämtning och normalisering
# ---------------------------------------------------------------------------

def _fetch_raw_transcript(episode_id: str, token: str) -> Optional[dict]:
    """
    Anropar Spotifys interna transkript-endpoint.
    Returnerar rå JSON-dict, eller None om episoden saknar transkript (404).
    Kastar RuntimeError vid nätverks-/serverfel.
    """
    url     = _TRANSCRIPT_URL.format(episode_id=episode_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "app-platform":  "WebPlayer",
        "User-Agent":    _UA,
        "Accept":        "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except Exception as e:
        raise RuntimeError(f"Nätverksfel mot transkript-endpoint: {e}") from e

    if resp.status_code == 404:
        logger.info("[spotify] Episod %s saknar transkript (404)", episode_id)
        return None
    if not resp.ok:
        raise RuntimeError(
            f"Transkript-endpoint svarade {resp.status_code}: {resp.text[:200]}"
        )
    return resp.json()


def _normalize(raw: dict) -> list[dict]:
    """
    Normaliserar Spotifys section-format till vigil-transkriptformat:
    [{start: float, end: float, text: str}, ...]

    Spotifys format har section-listor med antingen:
      - {"startMs": N, "endMs": N, "text": {"sentence": {"text": "..."}}}
      - {"startMs": N, "text": {"sentence": {"text": "..."}}}  (end saknas)
    End-tid härleds från nästa sections startMs när den saknas.
    """
    sections = raw.get("section") or raw.get("sections") or []
    segments: list[dict] = []

    for i, s in enumerate(sections):
        start_ms = s.get("startMs") or s.get("start_ms") or 0

        # Parsa text — kan vara sträng, dict med sentence, eller dict med text
        raw_text = s.get("text") or s.get("content") or ""
        if isinstance(raw_text, dict):
            sentence = raw_text.get("sentence") or {}
            text = sentence.get("text") or raw_text.get("text") or ""
        else:
            text = str(raw_text)
        text = text.strip()
        if not text:
            continue

        # end_ms: explicit, eller nästa sections start, eller +5 s som fallback
        end_ms = s.get("endMs") or s.get("end_ms")
        if not end_ms:
            next_start = sections[i + 1].get("startMs") if i + 1 < len(sections) else None
            end_ms = next_start if next_start and next_start > start_ms else (start_ms + 5000)

        segments.append(
            {
                "start": round(start_ms / 1000, 2),
                "end":   round(end_ms / 1000, 2),
                "text":  text,
            }
        )

    # Fallback: platt cue-lista (äldre eller alternativt format)
    if not segments:
        cues = raw.get("cues") or raw.get("transcript", {}).get("cues") or []
        for cue in cues:
            text = (cue.get("word") or cue.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start": round(cue.get("startTimeMs", 0) / 1000, 2),
                    "end":   round(cue.get("endTimeMs", 0) / 1000, 2),
                    "text":  text,
                }
            )

    return segments


# ---------------------------------------------------------------------------
# Spara transkript i vigil-standardformat
# ---------------------------------------------------------------------------

def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _save(item_id: int, segments: list[dict]) -> Path:
    """Sparar transkript som JSON (maskinläsbart) + TXT (debugläsbart)."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = TRANSCRIPTS_DIR / f"vigil_{item_id}.json"
    txt_path  = TRANSCRIPTS_DIR / f"vigil_{item_id}.txt"

    json_path.write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    txt_path.write_text(
        "\n".join(f"[{_fmt_ts(s['start'])}] {s['text']}" for s in segments),
        encoding="utf-8",
    )
    logger.info(
        "[spotify] Transkript sparat: %s (%d segment)", json_path.name, len(segments)
    )
    return json_path


# ---------------------------------------------------------------------------
# Huvudfunktion — anropas från downloader.py
# ---------------------------------------------------------------------------

def try_spotify_transcript(conn, item_id: int) -> bool:
    """
    Hämtar Spotifys transkript för ett köat item och sparar det direkt.

    Returnerar True  → transkript hämtat och sparat, item → transcribed
    Returnerar False → misslyckades (item lämnas oförändrat i queued)
    Övergår item till filtered_out om episoden bekräftat saknar transkript (404).

    Integration: anropas från download_item() i downloader.py när
    item.url matchar open.spotify.com/episode/. Undviker downloader →
    transcriber-flödet och hoppar direkt till transcribed.
    """
    item = conn.execute(
        "SELECT id, url, title FROM vigil_items WHERE id = ?", (item_id,)
    ).fetchone()
    if not item:
        logger.error("[spotify] Item %d finns inte i databasen", item_id)
        return False

    url        = item["url"]
    episode_id = _episode_id(url)
    if not episode_id:
        logger.error("[spotify] Kan inte extrahera episode-ID från: %s", url)
        return False

    sp_dc = os.getenv("SPOTIFY_SP_DC")
    if not sp_dc:
        logger.error(
            "[spotify] SPOTIFY_SP_DC saknas i .env — "
            "hämta cookien från DevTools → Application → Cookies på open.spotify.com"
        )
        return False

    title = (item["title"] or "")[:60]
    logger.info("[spotify] Hämtar transkript för item %d: %s", item_id, title or episode_id)

    # Hämta token
    try:
        token = _get_token(sp_dc)
    except RuntimeError as e:
        logger.error("[spotify] Tokenfel för item %d: %s", item_id, e)
        return False

    # Hämta transkript
    try:
        raw = _fetch_raw_transcript(episode_id, token)
    except RuntimeError as e:
        logger.error("[spotify] Transkriptfel för item %d: %s", item_id, e)
        return False

    if raw is None:
        # 404 — episoden saknar transkript, filtrera bort utan att försöka igen
        transition(conn, item_id, "filtered_out")
        return False

    segments = _normalize(raw)
    if not segments:
        logger.warning(
            "[spotify] Tomt transkript för item %d (rådata börjar: %s)",
            item_id,
            str(raw)[:200],
        )
        # Spara rådata för felsökning
        debug_path = DATA_DIR / f"spotify_raw_{item_id}.json"
        debug_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.warning("[spotify] Rådata sparad i %s", debug_path.name)
        transition(conn, item_id, "filtered_out")
        return False

    json_path = _save(item_id, segments)
    transition(conn, item_id, "transcribed", transcript_path=str(json_path))
    logger.info(
        "[spotify] Item %d → transcribed (%d segment, %s)",
        item_id,
        len(segments),
        json_path.name,
    )
    return True


# ---------------------------------------------------------------------------
# CLI — fristående test utan databas
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse, sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Spotify transkript-hämtare — clio-vigil",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exempel:
  # Testa direkt utan DB (kräver SPOTIFY_SP_DC i .env)
  python spotify_handler.py --url open.spotify.com/episode/3qnxNWeT8RHPSZd5SSFBYT

  # Kör mot vigil-item (kräver SPOTIFY_SP_DC i .env + vigil.db)
  python spotify_handler.py --item 3439

  # Visa cipher-info
  python spotify_handler.py --cipher-info
        """,
    )
    parser.add_argument("--url",         type=str, help="Spotify-episod-URL att testa")
    parser.add_argument("--item",        type=int, help="vigil item-ID att transkribera")
    parser.add_argument("--cipher-info", action="store_true", help="Visa cachat cipher-version")
    args = parser.parse_args()

    # --- Cipher-info ---
    if args.cipher_info:
        try:
            _, version = _load_cipher()
            print(f"Cipher version: {version}")
            if _SECRETS_CACHE.exists():
                cached = json.loads(_SECRETS_CACHE.read_text(encoding="utf-8"))
                age_h = (time.time() - cached.get("fetched_at", 0)) / 3600
                print(f"Cache ålder: {age_h:.1f} h")
        except RuntimeError as e:
            print(f"FEL: {e}")
        return

    # --- Testa mot URL direkt (utan DB) ---
    if args.url:
        episode_id = _episode_id(args.url)
        if not episode_id:
            print(f"Kan inte extrahera episode-ID från: {args.url}")
            sys.exit(1)
        sp_dc = os.getenv("SPOTIFY_SP_DC")
        if not sp_dc:
            print("SPOTIFY_SP_DC saknas i .env")
            sys.exit(1)
        try:
            token = _get_token(sp_dc)
            raw   = _fetch_raw_transcript(episode_id, token)
        except RuntimeError as e:
            print(f"FEL: {e}")
            sys.exit(1)
        if raw is None:
            print("Inget transkript tillgängligt för den här episoden (404)")
            sys.exit(0)
        segments = _normalize(raw)
        print(f"\n{len(segments)} segment hämtade:")
        for seg in segments[:8]:
            print(f"  [{_fmt_ts(seg['start'])}] {seg['text'][:80]}")
        if len(segments) > 8:
            print(f"  ... och {len(segments) - 8} till")
        return

    # --- Kör mot vigil-item ---
    if args.item:
        from orchestrator import init_db
        conn = init_db()
        ok   = try_spotify_transcript(conn, args.item)
        print("OK — transkript hämtat" if ok else "MISS — se loggen")
        conn.close()
        return

    parser.print_help()


if __name__ == "__main__":
    _main()
