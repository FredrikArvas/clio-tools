#!/usr/bin/env python3
"""
clio-fetch-iphone-audio — Hämtar WAV-filer från AudioShare (iPhone) till lokal mapp.

Användning:
    python main.py
    python main.py --dry-run
    python main.py --host 192.168.1.214 --dest "C:/Users/fredr/Dropbox/Audio/iPhone-inspelningar"
    python main.py --probe          # Testa vilken URL-mall som fungerar
"""

import argparse
import os
import re
import sys
import unicodedata
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_HOST = "192.168.1.214"
DEFAULT_DEST = r"C:\Users\fredr\Dropbox\Audio\iPhone-inspelningar"
CHUNK_SIZE   = 65_536
TIMEOUT_LIST = 15
TIMEOUT_FILE = 300

# URL-mallar att prova i ordning vid auto-probe
URL_TEMPLATES = [
    "direct",       # http://HOST/path  (enklast)
    "download",     # http://HOST/download?path=/path
    "get",          # http://HOST/get?path=/path
]

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')


def _normalize_name(name: str) -> str:
    """NFC-normalisera (iOS skickar NFD) och ersätt Windows-ogiltiga tecken med _."""
    return _ILLEGAL_CHARS.sub("_", unicodedata.normalize("NFC", name))


def _safe_tmp(dest_path: Path) -> Path:
    """Returnerar en .tmp-sökväg (redan normaliserat filnamn)."""
    return dest_path.with_suffix(".tmp")


def _build_url(host: str, path: str, template: str) -> str:
    if template == "direct":
        return f"http://{host}{quote(path)}"
    elif template == "download":
        return f"http://{host}/download?" + urlencode({"path": path})
    elif template == "get":
        return f"http://{host}/get?" + urlencode({"path": path})
    raise ValueError(f"Okänd URL-mall: {template}")


def list_remote_files(host: str) -> list[dict]:
    url  = f"http://{host}/list?path=/"
    resp = requests.get(url, timeout=TIMEOUT_LIST)
    resp.raise_for_status()
    return [e for e in resp.json() if "size" in e]


def probe_url_template(host: str, files: list[dict]) -> str:
    """Testar URL-mallar mot en liten fil och returnerar den som fungerar."""
    # Välj minsta filen för snabbt test
    test = min(files, key=lambda e: e["size"])
    for tmpl in URL_TEMPLATES:
        url = _build_url(host, test["path"], tmpl)
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                print(f"  ✓ fungerar: {tmpl}  ({url})")
                return tmpl
            else:
                print(f"  ✗ {r.status_code}: {tmpl}")
        except Exception as e:
            print(f"  ✗ fel: {tmpl}  ({e})")
    raise RuntimeError("Ingen URL-mall fungerade — är AudioShare igång på telefonen?")


def build_local_index(dest: Path) -> dict[str, int]:
    return {_normalize_name(p.name): p.stat().st_size for p in dest.glob("*.wav")}


def download_file(url: str, dest_path: Path, expected_size: int) -> bool:
    tmp = _safe_tmp(dest_path)
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT_FILE) as r:
            r.raise_for_status()
            downloaded = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                    f.write(chunk)
                    downloaded += len(chunk)
                    pct = downloaded * 100 // expected_size if expected_size else 0
                    print(
                        f"\r  {pct:3d}%  "
                        f"({downloaded / 1_048_576:.1f} / {expected_size / 1_048_576:.1f} MB)",
                        end="", flush=True,
                    )
        print()
        tmp.replace(dest_path)
        # Bevara ursprungligt inspelningsdatum från servern
        last_modified = r.headers.get("Last-Modified")
        if last_modified:
            try:
                ts = parsedate_to_datetime(last_modified).timestamp()
                os.utime(dest_path, (ts, ts))
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"\n  FEL: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="AudioShare → lokal mapp (inkrementell sync)")
    parser.add_argument("--host",    default=DEFAULT_HOST,  help="IP-adress till telefonen")
    parser.add_argument("--dest",    default=DEFAULT_DEST,  help="Lokal målmapp")
    parser.add_argument("--dry-run", action="store_true",   help="Visa vad som skulle laddas, gör inget")
    parser.add_argument("--probe",   action="store_true",   help="Testa URL-mallar och avsluta")
    args = parser.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    print(f"Hämtar fillista från {args.host}...")
    try:
        remote_files = list_remote_files(args.host)
    except Exception as e:
        print(f"Kunde inte nå {args.host}: {e}")
        sys.exit(1)

    print(f"  {len(remote_files)} filer på telefonen")

    if args.probe:
        print("\nProbar URL-mallar...")
        try:
            tmpl = probe_url_template(args.host, remote_files)
            print(f"\nAnvänd mall: --url-template {tmpl}")
        except RuntimeError as e:
            print(f"\n{e}")
            sys.exit(1)
        return

    # Auto-detektera URL-mall
    print("Detekterar nedladdnings-URL...")
    try:
        url_template = probe_url_template(args.host, remote_files)
    except RuntimeError as e:
        print(f"\n{e}")
        sys.exit(1)

    local_index = build_local_index(dest)

    to_download = []
    skipped     = 0
    overwrite   = set()

    for entry in remote_files:
        name       = _normalize_name(entry["name"])
        size       = entry["size"]
        local_size = local_index.get(name)
        if local_size == size:
            skipped += 1
        else:
            to_download.append({**entry, "local_name": name})
            if local_size is not None:
                overwrite.add(name)

    total_mb = sum(e["size"] for e in to_download) / 1_048_576
    print(
        f"\nResultat: {skipped} skip | {len(to_download)} att ladda "
        f"({total_mb:.0f} MB) | {len(overwrite)} skrivs om"
    )

    if not to_download:
        print("Allt är redan synkat.")
        return

    if args.dry_run:
        print("\n-- dry-run, ingen nedladdning --")
        for e in to_download:
            local_name = e["local_name"]
            tag = "  [SKRIV OM]" if local_name in overwrite else ""
            print(f"  {local_name}  ({e['size'] / 1_048_576:.1f} MB){tag}")
        return

    errors = 0
    for i, entry in enumerate(to_download, 1):
        local_name = entry["local_name"]
        size       = entry["size"]
        tag        = "  [skriver om]" if local_name in overwrite else ""
        print(f"\n[{i}/{len(to_download)}] {local_name}  ({size / 1_048_576:.1f} MB){tag}")
        url = _build_url(args.host, entry["path"], url_template)
        ok  = download_file(url, dest / local_name, size)
        if not ok:
            errors += 1

    print(
        f"\nKlar. {len(to_download) - errors} nedladdade, "
        f"{errors} fel, {skipped} hoppades över."
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
