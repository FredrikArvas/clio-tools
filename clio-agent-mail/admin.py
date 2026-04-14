"""
admin.py — Behörighetsadmin TUI för clio-agent-mail

Steg 1: Lista whitelistade användare → välj en
Steg 2: Visa nuvarande behörighet + lista alla projekt → välj projektkorg
Steg 3: Bekräfta → uppdatera permission-matrisen i Notion

Körning:
    python clio-agent-mail/admin.py
"""
from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from dotenv import load_dotenv as _ld
    for _env in (REPO_ROOT / ".env", SCRIPT_DIR / ".env"):
        if _env.exists():
            _ld(_env, override=False)
except ImportError:
    pass

# ── Färger ────────────────────────────────────────────────────────────────────
GRN = "\033[32m"
YEL = "\033[33m"
GRY = "\033[90m"
BLD = "\033[1m"
NRM = "\033[0m"
CYN = "\033[36m"
RED = "\033[31m"


def _parse_selection(text: str, max_n: int) -> list[int]:
    """
    Parsar urval-sträng till 0-baserade index.

    Exempel:
      "1,2,9"     → [0, 1, 8]
      "1-3,7-8"   → [0, 1, 2, 6, 7]
      "all"       → [0, 1, ..., max_n-1]
    """
    text = text.strip().lower()
    if text == "all":
        return list(range(max_n))
    result: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            try:
                for i in range(int(lo), int(hi) + 1):
                    if 1 <= i <= max_n:
                        result.add(i - 1)
            except ValueError:
                pass
        elif part.isdigit():
            i = int(part)
            if 1 <= i <= max_n:
                result.add(i - 1)
    return sorted(result)


def _load_env_and_config() -> tuple[str, configparser.ConfigParser]:
    """Returnerar (notion_token, cfg)."""
    token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN", "")
    cfg = configparser.ConfigParser()
    cfg.read(str(SCRIPT_DIR / "clio.config"), encoding="utf-8")
    return token, cfg


def _admin_account_scopes(cfg) -> None:
    """
    TUI för att hantera per-brevlåda kodord-scope (account_scopes.json).

    Visar alla konfigurerade konton med deras nuvarande scope,
    låter adminen välja ett konto och uppdatera dess kodord-lista.
    """
    import notion_data as nd

    db_raw = cfg.get("mail", "knowledge_notion_db_ids", fallback="")
    if not db_raw:
        print(f"\n{RED}Fel: knowledge_notion_db_ids saknas i clio.config{NRM}")
        return

    db_id = db_raw.split(",")[0].split(":")[0].strip()

    # Hämta projektlista och nuvarande scopes
    print(f"\n{GRY}Hämtar projekt och brevlåde-scopes...{NRM}")
    projects = nd.get_project_index(db_id)
    scopes = nd.get_all_account_scopes()

    if not scopes:
        print(f"\n{GRY}(account_scopes.json är tom eller saknas){NRM}")
        return

    print(f"\n{BLD}=== BREVLÅDE-SCOPE ==={NRM}\n")
    accounts = sorted(scopes.keys())
    for i, acct in enumerate(accounts, 1):
        s = scopes[acct]
        scope_str = ", ".join(f"#{k}" for k in s) if s else f"{GRN}(alla){NRM}"
        print(f"  {CYN}{i:>3}.{NRM}  {acct}@   {scope_str}")

    sel = input(f"\nVälj brevlåda (nummer, Enter=avsluta): ").strip()
    if not sel:
        return
    if not sel.isdigit() or not (1 <= int(sel) <= len(accounts)):
        print(f"{GRY}Ogiltigt val.{NRM}")
        return

    selected_account = accounts[int(sel) - 1]
    current_scope: list[str] = scopes[selected_account]

    print(f"\n{BLD}{'─' * 56}")
    print(f"  Brevlåda  : {selected_account}@")
    scope_display = ", ".join(f"#{k}" for k in current_scope) if current_scope else "(alla / obegränsad)"
    print(f"  Scope     : {scope_display}")
    print(f"{'─' * 56}{NRM}")

    if not projects:
        print(f"\n{GRY}(inga projekt hittades){NRM}")
        return

    print(f"\n{BLD}Tillgängliga projekt:{NRM}")
    print(f"  {GRY}{'Nr':>4}  {'Kodord':<14} {'Namn'}{NRM}")
    print(f"  {GRY}{'─' * 52}{NRM}")
    for i, p in enumerate(projects, 1):
        kw       = f"#{p['kodord']}" if p.get("kodord") else "—"
        name     = p.get("name", "")
        selected = f" {GRN}✓{NRM}" if p.get("kodord") in current_scope else ""
        print(f"  {CYN}{i:>4}.{NRM}  {kw:<14} {name}{selected}")

    print(f"\n  {GRY}Format: 1,2 | 1-3 | all | Enter=alla (obegränsad){NRM}")
    sel2 = input("Välj projekt för denna brevlåda: ").strip()

    if not sel2:
        # Tom inmatning = ta bort alla begränsningar
        chosen_kodord = []
        print(f"\n{GRY}(ingen begränsning — brevlådan ser alla projekt){NRM}")
    else:
        selected_indices = _parse_selection(sel2, len(projects))
        if not selected_indices:
            print(f"\n{GRY}Ogiltigt val — inga projekt valda.{NRM}")
            return
        chosen_kodord = [projects[i]["kodord"] for i in selected_indices if projects[i].get("kodord")]

    # Bekräfta
    print(f"\n{BLD}{'─' * 56}")
    print(f"  Brevlåda  : {selected_account}@")
    if chosen_kodord:
        print(f"  Scope     : {', '.join('#' + k for k in chosen_kodord)}")
    else:
        print(f"  Scope     : {GRN}(alla / obegränsad){NRM}")
    print(f"{BLD}{'─' * 56}{NRM}")

    confirm = input("Spara? (J/n): ").strip().lower()
    if confirm not in ("j", "y", "ja", "yes", ""):
        print(f"\n{GRY}Avbruten.{NRM}")
        return

    try:
        nd.save_account_scope(selected_account, chosen_kodord)
        if chosen_kodord:
            print(f"\n{GRN}✓ Scope uppdaterat: {selected_account}@ → {', '.join('#' + k for k in chosen_kodord)}{NRM}\n")
        else:
            print(f"\n{GRN}✓ Scope uppdaterat: {selected_account}@ → (alla projekt){NRM}\n")
    except Exception as e:
        print(f"\n{RED}Fel vid sparning: {e}{NRM}")


def main(argv=None) -> None:
    token, cfg = _load_env_and_config()

    if not token:
        print(f"\n{RED}Fel: NOTION_API_KEY saknas i .env{NRM}")
        return

    wl_page   = cfg.get("mail", "whitelist_notion_page_id",   fallback="")
    perm_page = cfg.get("mail", "permissions_notion_page_id", fallback="")
    db_raw    = cfg.get("mail", "knowledge_notion_db_ids",    fallback="")

    if not wl_page:
        print(f"\n{RED}Fel: whitelist_notion_page_id saknas i clio.config{NRM}")
        return

    print(f"\n{BLD}=== BEHÖRIGHETSADMIN — clio-agent-mail ==={NRM}\n")
    print(f"  {CYN}1.{NRM}  Hantera kodord-scope per användare")
    print(f"  {CYN}2.{NRM}  Hantera brevlåde-scope (account_scopes.json)")
    menu_sel = input(f"\nVälj (1/2, Enter=1): ").strip()

    if menu_sel == "2":
        _admin_account_scopes(cfg)
        return

    # ── STEG 1: Lista whitelistade användare ──────────────────────────────────
    print(f"\n{GRY}Hämtar whitelistade användare från Notion...{NRM}")

    import notion_data as nd
    whitelist = sorted(nd.get_whitelist(wl_page))

    if not whitelist:
        print(f"  {GRY}(vitlistan är tom){NRM}")
        return

    print(f"\n{BLD}Whitelistade användare:{NRM}")
    for i, email in enumerate(whitelist, 1):
        print(f"  {CYN}{i:>3}.{NRM} {email}")

    sel1 = input(f"\nVälj användare (nummer, Enter=avsluta): ").strip()
    if not sel1:
        return
    if not sel1.isdigit() or not (1 <= int(sel1) <= len(whitelist)):
        print(f"{GRY}Ogiltigt val.{NRM}")
        return

    selected_email = whitelist[int(sel1) - 1]

    # ── Hämta nuvarande behörighet ────────────────────────────────────────────
    from clio_access.notion_source import fetch_matrix, update_user_permission

    matrix = {}
    if perm_page:
        print(f"\n{GRY}Hämtar behörighetsmatris...{NRM}")
        matrix = fetch_matrix(perm_page, token).get("emails", {})

    current = matrix.get(selected_email, {})
    current_level = current.get("level", "whitelisted")
    current_scope: list[str] = current.get("kodord_scope", [])

    print(f"\n{BLD}{'─' * 56}")
    print(f"  Användare : {selected_email}")
    print(f"  Nivå      : {current_level}")
    scope_display = ", ".join(f"#{k}" for k in current_scope) if current_scope else "(alla / obegränsad)"
    print(f"  Kodord    : {scope_display}")
    print(f"{'─' * 56}{NRM}")

    # ── STEG 2: Lista projekt ──────────────────────────────────────────────────
    if not db_raw:
        print(f"\n{RED}Fel: knowledge_notion_db_ids saknas i clio.config{NRM}")
        return

    db_id = db_raw.split(",")[0].split(":")[0].strip()
    print(f"\n{GRY}Hämtar projekt från Notion...{NRM}")
    projects = nd.get_project_index(db_id)

    if not projects:
        print(f"  {GRY}(inga projekt hittades){NRM}")
        return

    print(f"\n{BLD}Tillgängliga projekt:{NRM}")
    print(f"  {GRY}{'Nr':>4}  {'Kodord':<14} {'Namn'}{NRM}")
    print(f"  {GRY}{'─' * 52}{NRM}")
    for i, p in enumerate(projects, 1):
        kw       = f"#{p['kodord']}" if p.get("kodord") else "—"
        name     = p.get("name", "")
        selected = f" {GRN}✓{NRM}" if p.get("kodord") in current_scope else ""
        print(f"  {CYN}{i:>4}.{NRM}  {kw:<14} {name}{selected}")

    print(f"\n  {GRY}Format: 1,2,9 | 1-3,7-8 | all | Enter=behåll nuvarande{NRM}")
    sel2 = input("Välj projektkorg: ").strip()

    if not sel2:
        print(f"\n{GRY}(ingen ändring — avslutar){NRM}")
        return

    selected_indices = _parse_selection(sel2, len(projects))
    if not selected_indices:
        print(f"\n{GRY}Ogiltigt val — inga projekt valda.{NRM}")
        return

    chosen_kodord = [projects[i]["kodord"] for i in selected_indices if projects[i].get("kodord")]

    # ── STEG 3: Skrivrätt (:rw) ───────────────────────────────────────────────
    current_write: list[str] = current.get("kodord_write", [])

    print(f"\n{BLD}Skrivrätt — vilka projekt ska användaren kunna uppdatera?{NRM}")
    for i, k in enumerate(chosen_kodord, 1):
        mark = f"  {GRN}[rw]{NRM}" if k in current_write else ""
        print(f"  {CYN}{i:>3}.{NRM}  #{k}{mark}")
    print(f"\n  {GRY}Format: 1,2 | all | Enter=ingen skrivrätt{NRM}")
    sel3 = input("Skrivrätt för: ").strip()

    write_indices = _parse_selection(sel3, len(chosen_kodord)) if sel3 else []
    chosen_write = [chosen_kodord[i] for i in write_indices]

    # ── STEG 4: Bekräfta + spara ──────────────────────────────────────────────
    print(f"\n{BLD}{'─' * 56}")
    print(f"  Användare : {selected_email}")
    for k in chosen_kodord:
        perm = f"{GRN}:rw{NRM}" if k in chosen_write else f"{GRY}:r {NRM}"
        print(f"  #{k:<14} {perm}")
    if current_level not in ("coded", "admin", "write") and chosen_kodord:
        print(f"  Nivå      : {YEL}uppgraderas till 'coded' (nuv: {current_level}){NRM}")
    print(f"{BLD}{'─' * 56}{NRM}")

    confirm = input("Spara till Notion? (J/n): ").strip().lower()
    if confirm not in ("j", "y", "ja", "yes", ""):
        print(f"\n{GRY}Avbruten.{NRM}")
        return

    if not perm_page:
        print(f"\n{RED}Fel: permissions_notion_page_id saknas — kan inte spara.{NRM}")
        return

    new_level = current_level if current_level in ("coded", "admin", "write") else "coded"

    try:
        update_user_permission(
            perm_page,
            token,
            selected_email,
            level=new_level,
            kodord_scope=chosen_kodord,
            kodord_write=chosen_write,
        )
        r_only = [k for k in chosen_kodord if k not in chosen_write]
        print(f"\n{GRN}✓ Behörighet uppdaterad för {selected_email}.{NRM}")
        if r_only:
            print(f"  Läs:   {', '.join(f'#{k}' for k in r_only)}")
        if chosen_write:
            print(f"  Skriv: {', '.join(f'#{k}' for k in chosen_write)}")
        print()
    except Exception as e:
        print(f"\n{RED}Fel vid sparning: {e}{NRM}")


if __name__ == "__main__":
    main(sys.argv[1:])
