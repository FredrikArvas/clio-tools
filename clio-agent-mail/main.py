"""
main.py — huvudloop för clio-agent-mail

Startar IMAP-polling och kör ett pass per konfigurerat intervall.
Kan köras som systemd-tjänst eller anropas direkt av agent.

Flaggor:
  --dry-run   Kör hela flödet utan att skicka mail eller skriva till databasen
  --once      Kör ett enda poll-pass och avsluta (agent-ready / CI-testning)
  --debug     Aktivera DEBUG-loggning inkl. HTTP-trafik

Publikt API (agent-ready):
  main(argv=None)   — startar loop eller kör --once/--dry-run
  poll_once(config) — hämtar nya mail från alla konfigurerade konton

Mail-routing och svarsgenerering ligger i handlers.py.
Rena hjälpfunktioner ligger i helpers.py.
"""
import argparse
import configparser
import io as _io
import logging
import os
import sys
import time
from datetime import datetime as _dt
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent

# Gör clio_core tillgängligt även när skriptet körs med system-Python
# (t.ex. via clio.py som använder sys.executable — inte alltid venv-Python)
_clio_core_path = ROOT_DIR / "clio-core"
if str(_clio_core_path) not in sys.path:
    sys.path.insert(0, str(_clio_core_path))

# Ladda root-.env först (ANTHROPIC_API_KEY, NOTION_API_KEY)
# sedan modul-.env (IMAP_PASSWORD_CLIO, IMAP_PASSWORD_INFO) — override=True
# så att modul-specifika värden vinner om samma nyckel skulle finnas i båda.
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=True)

from clio_core.utils import t, set_language

import state
import imap_client
import smtp_client
import approval as approval_module

import handlers

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(
        _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        if hasattr(sys.stdout, "buffer") else sys.stdout
    )],
)
logger = logging.getLogger("clio-mail")

# Tredjepartsloggers tystas tills --debug aktiveras
_NOISY_LOGGERS = [
    "httpcore", "httpx", "anthropic", "anthropic._base_client",
    "urllib3", "notion_client",
]


def _set_log_level(debug: bool):
    root_level = logging.DEBUG if debug else logging.INFO
    logging.getLogger().setLevel(root_level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(
            logging.DEBUG if debug else logging.WARNING
        )


# ── Konfiguration ─────────────────────────────────────────────────────────────

def load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None)
    config_path = BASE_DIR / "clio.config"
    if not config_path.exists():
        raise FileNotFoundError(t("mail_config_missing", path=config_path))
    config.read(str(config_path), encoding="utf-8")

    # Injicera lösenord från miljövariabler (skrivs aldrig i clio.config)
    # Täcker alla konton i accounts-listan + info (för SMTP-sändning)
    if config.has_section("mail"):
        accounts_raw = config.get("mail", "accounts", fallback="clio,info")
        account_keys = [a.strip() for a in accounts_raw.split(",") if a.strip()]
        for key in set(account_keys + ["info"]):
            env_key = f"IMAP_PASSWORD_{key.upper()}"
            val = os.environ.get(env_key)
            if val:
                config.set("mail", f"imap_password_{key}", val)
    return config


# ── Polling ───────────────────────────────────────────────────────────────────

def poll_once(config) -> list:
    """
    Hämtar nya mail från alla konfigurerade IMAP-konton (accounts i clio.config).
    Returnerar lista av MailItem.
    """
    accounts_raw = config.get("mail", "accounts", fallback="clio")
    account_keys = [a.strip() for a in accounts_raw.split(",") if a.strip()]
    items = []
    for account_key in account_keys:
        password = config.get("mail", f"imap_password_{account_key}", fallback="").strip()
        if not password:
            logger.debug(f"[{account_key}@] No password configured — skipping")
            continue
        try:
            fetched = imap_client.fetch_unseen(config, account_key)
            logger.info(f"[{account_key}@] {len(fetched)} new mail(s) fetched")
            items.extend(fetched)
        except Exception as e:
            logger.error(f"Polling failed for {account_key}: {e}")
    return items


# ── Poll-cykel ────────────────────────────────────────────────────────────────

def run_cycle(config, dry_run: bool = False) -> bool:
    """
    Kör ett komplett poll-pass: hämta mail + hantera godkännanden.
    Returnerar True om minst ett nytt mail hämtades.
    """
    logger.info("─── Poll-cykel startar ───")

    mail_items = poll_once(config)
    for item in mail_items:
        handlers.process_mail(item, config, dry_run)

    def _smtp_send(**kwargs):
        smtp_client.send_email(config=config, dry_run=dry_run, **kwargs)

    approval_module.check_approvals(
        config=config,
        smtp_send_fn=_smtp_send,
        dry_run=dry_run,
    )
    handlers.check_flagged_responses(config)

    # Kör bara om det finns WAITING-mail — undviker onödig Notion-hämtning
    import sqlite3 as _sql
    with _sql.connect(str(state.DB_PATH)) as _con:
        _has_waiting = _con.execute(
            "SELECT 1 FROM mail WHERE status = ? LIMIT 1", (state.STATUS_WAITING,)
        ).fetchone()
    if _has_waiting:
        handlers._auto_process_newly_whitelisted(config, dry_run)

    logger.info("─── Poll-cykel klar ───")
    return len(mail_items) > 0


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t("mail_description")
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=t("mail_dry_run_help"),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help=t("mail_once_help"),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG logging incl. HTTP traffic (default: INFO only)",
    )
    args = parser.parse_args(argv)

    _set_log_level(args.debug)

    config = load_config()

    state.init_db()

    interval = int(config.get("mail", "poll_interval_seconds", fallback="300"))

    if args.once or args.dry_run:
        run_cycle(config, dry_run=args.dry_run)
        return

    burst_interval = int(config.get("mail", "poll_interval_burst_seconds", fallback="15"))
    burst_duration = int(config.get("mail", "poll_burst_duration_seconds", fallback="300"))
    night_interval = int(config.get("mail", "poll_interval_night_seconds", fallback="900"))
    night_start    = int(config.get("mail", "poll_night_start_hour", fallback="22"))
    night_end      = int(config.get("mail", "poll_night_end_hour",   fallback="6"))
    last_activity = 0.0          # tidsstämpel för senaste mail

    logger.info(
        f"clio-agent-mail starting. "
        f"Day: {interval}s, Night ({night_start:02d}–{night_end:02d}): {night_interval}s, "
        f"Burst: {burst_interval}s for {burst_duration}s after activity"
    )
    while True:
        try:
            had_mail = run_cycle(config)
            if had_mail:
                last_activity = time.time()
        except Exception as e:
            logger.error(f"Unexpected error in poll cycle: {e}", exc_info=True)

        hour = _dt.now().hour
        if night_start <= hour or hour < night_end:
            base_interval = night_interval
            mode_label = "natt"
        else:
            base_interval = interval
            mode_label = "dag"

        since_activity = time.time() - last_activity
        if last_activity and since_activity < burst_duration:
            sleep_time = burst_interval
            remaining = int(burst_duration - since_activity)
            logger.info(f"Burst mode active — next poll in {sleep_time}s ({remaining}s remaining)")
        else:
            sleep_time = base_interval
            logger.debug(f"Mode: {mode_label} — next poll in {sleep_time}s")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
