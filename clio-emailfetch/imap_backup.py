"""
imap_backup.py

Hämtar alla mail via IMAP och sparar dem som .eml-filer.
Filnamn: YYYY-MM-DD_Subject.eml  (filens datum = mailets datum)
Mappar:  <backup_dir>/<konto>/<imap-mapp>/

Konfiguration läses från clio.config [emailfetch].
Inloggningsuppgifter hämtas från OS Credential Manager via keyring.
Kör setup_credentials.py först om du inte redan gjort det.

Användning:
    python imap_backup.py
    python imap_backup.py --dry-run
"""

import base64
import configparser
import email as email_lib
import email.header
import email.utils
import imaplib
import json
import logging
import os
import re
import sys
import keyring
from datetime import datetime, timezone
from pathlib import Path

__version__ = "1.1.0"

_ROOT      = Path(__file__).parent.parent   # clio-tools/
STATE_FILE = Path(__file__).parent / "backup_state.json"
LOG_FILE   = Path(__file__).parent / "imap_backup.log"

# ── Defaults (används om clio.config saknar [emailfetch]) ─────────────────────
_DEFAULTS = {
    "imap_host":    "imap.one.com",
    "imap_port":    "993",
    "service_name": "imap_three_com",
    "backup_dir":   "",
    "accounts":     "",
}


def _load_config() -> dict:
    """Läser [emailfetch] från clio.config. Returnerar dict med settings."""
    cfg = configparser.ConfigParser()
    config_path = _ROOT / "clio.config"
    if config_path.exists():
        cfg.read(config_path, encoding="utf-8")

    def _get(key):
        try:
            v = cfg.get("emailfetch", key)
            return v.strip().strip('"').strip("'")
        except (configparser.NoSectionError, configparser.NoOptionError):
            return _DEFAULTS.get(key, "")

    accounts_raw = _get("accounts")
    accounts = [a.strip() for a in accounts_raw.split(",") if a.strip()]

    return {
        "imap_host":    _get("imap_host")    or _DEFAULTS["imap_host"],
        "imap_port":    int(_get("imap_port") or _DEFAULTS["imap_port"]),
        "service_name": _get("service_name") or _DEFAULTS["service_name"],
        "backup_dir":   _get("backup_dir"),
        "accounts":     accounts,
    }


def load_state() -> dict:
    """Läser in tidigare UID-state från JSON-fil."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    """Sparar UID-state till JSON-fil."""
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def decode_imap_utf7(s: str) -> str:
    """Avkodar IMAP Modified UTF-7 (RFC 3501) till vanlig unicode-sträng.
    T.ex. 'INBOX.&AMQ-garbyte' → 'INBOX.Ägarbyte'
    """
    result = []
    i = 0
    while i < len(s):
        if s[i] == "&":
            j = s.find("-", i + 1)
            if j == -1:
                result.append(s[i:])
                break
            encoded = s[i + 1 : j]
            if encoded == "":
                result.append("&")
            else:
                b64 = encoded.replace(",", "/")
                pad = len(b64) % 4
                if pad:
                    b64 += "=" * (4 - pad)
                decoded_bytes = base64.b64decode(b64)
                result.append(decoded_bytes.decode("utf-16-be"))
            i = j + 1
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def sanitize_folder_name(name: str) -> str:
    """Gör mappnamn säkra att använda som Windows-katalognamn."""
    # Avkoda IMAP Modified UTF-7 → riktig text
    try:
        name = decode_imap_utf7(name)
    except Exception:
        pass
    # Ta bort tecken som inte är tillåtna i Windows filsystemet
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name.strip(". ") or "_"


def decode_subject(header_value) -> str:
    """Avkodar ett mail-Subject-fält (hanterar =?utf-8?...?= m.m.)"""
    if not header_value:
        return "(inget ämne)"
    parts = email.header.decode_header(header_value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                decoded.append(part.decode("latin-1", errors="replace"))
        else:
            decoded.append(str(part))
    return "".join(decoded).strip() or "(inget ämne)"


def parse_email_date(msg) -> datetime:
    """Returnerar mailets datum som datetime. Faller tillbaka på nu."""
    date_str = msg.get("Date", "")
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(tz=timezone.utc)


def make_eml_path(out_dir: str, msg, uid_str: str) -> str:
    """Bygger filnamn: YYYY-MM-DD_Subject.eml  (hanterar dubletter)."""
    dt = parse_email_date(msg)
    date_part = dt.strftime("%Y-%m-%d")
    subject_raw = decode_subject(msg.get("Subject"))
    subject_safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", subject_raw).strip(". ")
    subject_safe = subject_safe[:80] or "(inget ämne)"

    base = f"{date_part}_{subject_safe}"
    path = os.path.join(out_dir, f"{base}.eml")
    counter = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{base}_{counter}.eml")
        counter += 1
    return path, dt


def backup_account(email: str, password: str, state: dict, cfg: dict) -> None:
    log = logging.getLogger(__name__)
    print(f"\n{'='*50}")
    print(f"Konto: {email}")
    log.info(f"Backup: {email}")

    with imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"]) as imap:
        imap.login(email, password)
        print(f"  Inloggad.")

        # Lista alla IMAP-mappar
        status, folder_list = imap.list()
        if status != "OK":
            print(f"  FEL: Kunde inte lista mappar.")
            return

        folders = []
        for item in folder_list:
            decoded = item.decode()
            match = re.search(r'\) "." "?(.+?)"?\s*$', decoded)
            if match:
                folder_name = match.group(1).strip().strip('"')
                if folder_name:
                    folders.append(folder_name)

        decoded_names = [decode_imap_utf7(f) for f in folders]
        print(f"  Hittade {len(folders)} mappar: {', '.join(decoded_names)}")

        for folder in folders:
            state_key = f"{email}/{folder}"
            backup_folder(imap, email, folder, state, state_key, cfg["backup_dir"])

    print(f"  Klar: {email}")


def backup_folder(imap: imaplib.IMAP4_SSL, email: str, folder: str, state: dict, state_key: str, backup_dir: str = "") -> None:
    status, _ = imap.select(f'"{folder}"', readonly=True)
    if status != "OK":
        print(f"    [SKIP] {decode_imap_utf7(folder)} — kunde inte öppna.")
        return

    # Använd IMAP UID (stabila, ändras inte vid radering)
    status, data = imap.uid("search", None, "ALL")
    if status != "OK" or not data[0]:
        print(f"    [TOM]  {decode_imap_utf7(folder)}")
        state[state_key] = []
        return

    current_uids = set(data[0].decode().split())
    prev_uids    = set(state.get(state_key, []))

    nytt     = current_uids - prev_uids   # Nya på servern sedan sist
    raderade = prev_uids - current_uids   # Raderade från servern sedan sist

    folder_safe = sanitize_folder_name(folder)
    out_dir = Path(backup_dir) / sanitize_folder_name(email) / folder_safe
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = str(out_dir)

    nedladdade = 0
    for uid in current_uids:
        status, msg_data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not msg_data or not msg_data[0]:
            continue

        raw_email = msg_data[0][1]
        msg = email_lib.message_from_bytes(raw_email)
        filepath, mail_dt = make_eml_path(out_dir, msg, uid)

        if os.path.exists(filepath):
            continue  # Redan nerladdad

        with open(filepath, "wb") as f:
            f.write(raw_email)

        try:
            ts = mail_dt.timestamp()
            os.utime(filepath, (ts, ts))
        except Exception:
            pass

        nedladdade += 1

    # Uppdatera state med nuvarande UID-lista
    state[state_key] = list(current_uids)

    totalt   = len(current_uids)
    folder_display = decode_imap_utf7(folder)

    # Bygg statusrad med ändringar om de finns
    extra = []
    if nytt:
        extra.append(f"{len(nytt)} nytt")
    if raderade:
        extra.append(f"{len(raderade)} raderade")
    extra_str = f", {', '.join(extra)}" if extra else ""

    print(f"    {folder_display:<30} {nedladdade:>4} nedladdade  ({totalt} totalt{extra_str})")


def parse_args(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="imap_backup — IMAP e-postbackup")
    p.add_argument("--dry-run", action="store_true", help="Visa vad som skulle laddas ned utan att spara")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)

    # Sätt upp loggning till fil + stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    log = logging.getLogger(__name__)

    cfg = _load_config()

    if not cfg["backup_dir"]:
        log.error("backup_dir är inte konfigurerat. Sätt [emailfetch] backup_dir i clio.config.")
        sys.exit(1)

    if not cfg["accounts"]:
        log.error("accounts är inte konfigurerat. Sätt [emailfetch] accounts i clio.config.")
        sys.exit(1)

    log.info("=== IMAP Backup ===")
    log.info(f"Server: {cfg['imap_host']}:{cfg['imap_port']}")
    log.info(f"Sparas i: {cfg['backup_dir']}")
    if args.dry_run:
        log.info("[DRY RUN — ingenting sparas]")

    state = load_state()
    errors = 0

    for account in cfg["accounts"]:
        password = keyring.get_password(cfg["service_name"], account)
        if not password:
            log.warning(f"[HOPPAR ÖVER] {account} — inga credentials sparade. Kör setup_credentials.py.")
            continue
        try:
            backup_account(account, password, state, cfg)
        except imaplib.IMAP4.error as e:
            log.error(f"IMAP-fel för {account}: {e}")
            errors += 1
        except Exception as e:
            log.error(f"Oväntat fel för {account}: {e}")
            errors += 1

    save_state(state)
    log.info("=== Backup klar ===")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
