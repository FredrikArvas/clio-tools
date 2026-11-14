"""
clio-agent-gmail — hämtar bilagor från Gmail via IMAP

Användning:
    python main.py                  # kör alla jobb
    python main.py --job bauhaus    # kör ett specifikt jobb
    python main.py --list           # lista konfigurerade jobb
    python main.py --add-job        # lägg till nytt jobb interaktivt
"""
import argparse
import configparser
import os
import re
import sys
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
ROOT_DIR = BASE_DIR.parent

# Ladda .env: root-nivå, sedan modul-nivå (override)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass


def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(BASE_DIR / "clio.config", encoding="utf-8")
    return cfg


def _print_jobs(cfg: configparser.ConfigParser) -> None:
    jobs = [j.strip() for j in cfg.get("gmail", "jobs", fallback="").split(",") if j.strip()]
    print(f"\nKonfigurerade jobb ({len(jobs)}):")
    for key in jobs:
        section = f"job_{key}"
        desc       = cfg.get(section, "desc",       fallback=key)
        from_addr  = cfg.get(section, "from",       fallback="?")
        target_dir = cfg.get(section, "target_dir", fallback="?")
        account    = cfg.get(section, "account",    fallback="?")
        print(f"  [{key}]  {desc}")
        print(f"          Konto: {account}  |  Från: {from_addr}")
        print(f"          Mapp:  {target_dir}")


def _slug(text: str) -> str:
    """Gör en sträng till ett giltigt config-nyckelnamn."""
    return re.sub(r"[^a-z0-9_]", "_", text.lower().strip()).strip("_") or "jobb"


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val if val else default


def _add_job(cfg: configparser.ConfigParser) -> None:
    cfg_path = BASE_DIR / "clio.config"
    accounts = [a.strip() for a in cfg.get("gmail", "accounts", fallback="").split(",") if a.strip()]

    print("\n── Lägg till nytt Gmail-jobb ─────────────────────")

    # Jobbnamn/nyckel
    raw_name = _ask("Jobbnamn (t.ex. byggmax)")
    job_key  = _slug(raw_name)
    if cfg.has_section(f"job_{job_key}"):
        print(f"  Jobb [{job_key}] finns redan. Avbryter.")
        return

    # Konto
    if len(accounts) == 1:
        account = accounts[0]
        print(f"  Konto: {account} (enda kontot)")
    else:
        account = _ask(f"Konto ({', '.join(accounts)})", accounts[0])

    desc       = _ask("Beskrivning", f"{raw_name.capitalize()} fakturor")
    from_addr  = _ask("Avsändar-e-post (from)")
    target_dir = _ask("Målmapp (absolut sökväg)")
    extensions = _ask("Filändelser", ".pdf")

    # Bekräfta
    print(f"\n  Jobb:        [{job_key}]")
    print(f"  Konto:       {account}")
    print(f"  Beskrivning: {desc}")
    print(f"  Från:        {from_addr}")
    print(f"  Mapp:        {target_dir}")
    print(f"  Filändelser: {extensions}")
    confirm = _ask("\nSpara? (j/n)", "j").lower()
    if confirm != "j":
        print("  Avbruten.")
        return

    # Lägg till sektion i cfg
    section = f"job_{job_key}"
    cfg.add_section(section)
    cfg.set(section, "account",    account)
    cfg.set(section, "desc",       desc)
    cfg.set(section, "from",       from_addr)
    cfg.set(section, "target_dir", target_dir)
    cfg.set(section, "extensions", extensions)

    # Lägg till i jobs-listan
    existing_jobs = cfg.get("gmail", "jobs", fallback="")
    job_list = [j.strip() for j in existing_jobs.split(",") if j.strip()]
    if job_key not in job_list:
        job_list.append(job_key)
    cfg.set("gmail", "jobs", ", ".join(job_list))

    with open(cfg_path, "w", encoding="utf-8") as f:
        cfg.write(f)

    print(f"\n  ✓ Jobb [{job_key}] sparat i clio.config")


def main() -> None:
    parser = argparse.ArgumentParser(description="clio-agent-gmail")
    parser.add_argument("--job",      help="Kör ett specifikt jobb (nyckel från clio.config)")
    parser.add_argument("--list",     action="store_true", help="Lista konfigurerade jobb")
    parser.add_argument("--add-job",  action="store_true", help="Lägg till nytt jobb interaktivt")
    args = parser.parse_args()

    cfg = _load_config()

    if args.list:
        _print_jobs(cfg)
        return

    if args.add_job:
        _add_job(cfg)
        return

    sys.path.insert(0, str(BASE_DIR))
    from fetch import run_job, run_all_jobs

    if args.job:
        print(f"\nclio-agent-gmail — kör jobb: {args.job}")
        result = run_job(cfg, args.job)
        results = [result]
    else:
        print("\nclio-agent-gmail — kör alla jobb")
        results = run_all_jobs(cfg)

    print("\n" + "-" * 50)
    for r in results:
        print(f"[{r.job}]  sparade: {len(r.saved)} | finns redan: {len(r.already_exists)} | ovriga: {len(r.skipped)}")
        for err in r.errors:
            print(f"  FEL: {err}")
    print("-" * 50)


if __name__ == "__main__":
    main()
