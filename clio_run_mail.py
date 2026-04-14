"""
clio_run_mail.py
Mail-helpers och launcher för clio-agent-mail.
"""

from __future__ import annotations

import configparser
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from clio_menu import (
    BackToMenu, _input,
    GRN, YEL, GRY, BLD, NRM,
    save_state,
    menu_select, menu_text, menu_pause,
)

try:
    from config.clio_utils import t
except ImportError:
    def t(key, **kwargs): return key


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _mail_whitelist(tool: dict, state: dict) -> None:
    """Lägg till e-postadress i Notion-vitlistan för clio@."""
    cfg_path = tool["script"].parent / "clio.config"
    if not cfg_path.exists():
        print(f"\n{GRY}clio.config hittades inte: {cfg_path}{NRM}")
        menu_pause()
        return

    cfg = configparser.ConfigParser()
    cfg.read(str(cfg_path), encoding="utf-8")
    page_id = cfg.get("mail", "whitelist_notion_page_id", fallback="")
    if not page_id:
        print(f"\n{GRY}whitelist_notion_page_id saknas i clio.config{NRM}")
        menu_pause()
        return

    addr = menu_text("\nE-postadress att vitlista") or ""
    if not addr or "@" not in addr:
        print(f"{GRY}Ogiltig adress.{NRM}")
        menu_pause()
        return

    env_root = tool["script"].parent.parent / ".env"
    env_mod  = tool["script"].parent / ".env"
    for f in (env_root, env_mod):
        if f.exists():
            try:
                from dotenv import load_dotenv as _ld
                _ld(f, override=False)
            except ImportError:
                pass

    notion_token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")
    if not notion_token:
        print(f"\n{GRY}NOTION_API_KEY / NOTION_TOKEN saknas i .env{NRM}")
        menu_pause()
        return

    try:
        from notion_client import Client as _NC
        client = _NC(auth=notion_token)
        client.blocks.children.append(
            block_id=page_id,
            children=[{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": addr}}]
                }
            }]
        )
        print(f"\n{GRN}✓ {addr} tillagd i vitlistan.{NRM}")
    except Exception as e:
        print(f"\n{GRY}Fel: {e}{NRM}")
    menu_pause()


def _mail_log(tool: dict, state: dict) -> None:
    """Visar hanterade mail och låter Fredrik åtgärda väntande."""
    db_path = tool["script"].parent / "state.db"
    if not db_path.exists():
        print(f"\n{GRY}state.db hittades inte — inget mail har hanterats ännu.{NRM}")
        menu_pause()
        return

    status_color = {
        "NEW": YEL, "PENDING": YEL, "SENT": GRN,
        "FLAGGED": GRY, "REJECTED": GRY, "WAITING": YEL,
    }
    status_label = {
        "NEW": "NY", "PENDING": "VÄNTAR-GODK", "SENT": "SKICKAT",
        "FLAGGED": "FLAGGAD", "REJECTED": "AVVISAD", "WAITING": "⏳ VÄNTAR",
    }

    def _addr(sender):
        m = re.search(r"<([^>]+)>", sender or "")
        return (m.group(1) if m else sender or "?").lower()

    def _load(con, status_filter, n):
        if status_filter:
            return con.execute(
                "SELECT id, date_received, sender, subject, status, body "
                "FROM mail WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status_filter, n)
            ).fetchall()
        return con.execute(
            "SELECT id, date_received, sender, subject, status, body "
            "FROM mail ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()

    def _print_list(rows, numbered=False):
        print(f"\n{BLD}{'─' * 82}")
        prefix = "    " if not numbered else "  # "
        print(f"{prefix}{'Datum':<17} {'Avsändare':<28} {'Ämne':<22} {'Status'}")
        print(f"{'─' * 82}{NRM}")
        for i, row in enumerate(rows, 1):
            mail_id, date, sender, subject, status, body = row
            date_s    = (date or "?")[:16]
            sender_s  = _addr(sender)[:27]
            subject_s = (subject or "")[:21]
            col   = status_color.get(status, NRM)
            label = status_label.get(status, status)
            idx = f"[{i}]" if numbered else "   "
            print(f"  {idx} {date_s:<17} {sender_s:<28} {subject_s:<22} {col}{label}{NRM}")

    _FILTER_CHOICES = [
        "1. Väntar på åtgärd  (standard)",
        "2. Alla",
        "3. Skickade",
        "4. Flaggade / avvisade",
    ]
    f_choice = menu_select("Maillogg — visa:", _FILTER_CHOICES)
    if f_choice is None:
        return
    filter_map = {"1": "WAITING", "2": None, "3": "SENT", "4": "FLAGGED"}
    status_filter = filter_map.get(f_choice[0], "WAITING")

    n_raw = menu_text("Antal att visa", default="20") or "20"
    n = int(n_raw) if n_raw.isdigit() else 20

    try:
        con = sqlite3.connect(str(db_path))
        rows = _load(con, status_filter, n)
    except Exception as e:
        print(f"\n{GRY}Fel vid läsning av databas: {e}{NRM}")
        menu_pause()
        return

    if not rows:
        print(f"\n  {GRY}(inga mail med detta filter){NRM}")
        con.close()
        menu_pause()
        return

    numbered = (status_filter == "WAITING")
    _print_list(rows, numbered=numbered)

    waiting_count = sum(1 for r in rows if r[4] == "WAITING")
    if waiting_count:
        print(f"\n  {YEL}⏳ {waiting_count} mail väntar på vitlistningsbeslut{NRM}")
    print(f"{BLD}{'─' * 82}{NRM}")

    if not numbered:
        con.close()
        menu_pause()
        return

    sel = menu_text("\nVälj mail för åtgärd (nummer, Enter=avsluta)") or ""
    if not sel.isdigit() or not (1 <= int(sel) <= len(rows)):
        con.close()
        return

    selected = rows[int(sel) - 1]
    mail_id, date, sender, subject, status, body = selected
    sender_email = _addr(sender)

    print(f"\n{BLD}{'─' * 60}")
    print(f"Från:  {sender}")
    print(f"Ämne:  {subject or '(tomt)'}")
    print(f"Datum: {(date or '')[:16]}")
    print(f"{'─' * 60}{NRM}")
    print((body or "")[:600])
    if body and len(body) > 600:
        print(f"{GRY}[...]{NRM}")
    print(f"\n{BLD}{'─' * 60}{NRM}")

    action_choice = menu_select("\nÅtgärd:", [
        "V — Vitlista  (nästa poll skickar svar)",
        "S — Svartlista",
        "B — Behåll olistad (hållsvaret är redan skickat)",
    ])
    if action_choice is None:
        con.close()
        return
    action = action_choice[0].upper()

    cfg_path = tool["script"].parent / "clio.config"
    cfg = configparser.ConfigParser()
    cfg.read(str(cfg_path), encoding="utf-8")
    wl_page = cfg.get("mail", "whitelist_notion_page_id", fallback="")

    env_root = tool["script"].parent.parent / ".env"
    env_mod  = tool["script"].parent / ".env"
    for f in (env_root, env_mod):
        if f.exists():
            try:
                from dotenv import load_dotenv as _ld
                _ld(f, override=False)
            except ImportError:
                pass
    notion_token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")

    if action == "V":
        added = False
        if wl_page and notion_token:
            try:
                from notion_client import Client as _NC
                _NC(auth=notion_token).blocks.children.append(
                    block_id=wl_page,
                    children=[{"object": "block", "type": "paragraph",
                               "paragraph": {"rich_text": [{"type": "text",
                                             "text": {"content": sender_email}}]}}]
                )
                added = True
            except Exception as e:
                print(f"{GRY}Notion-fel: {e}{NRM}")
        if added:
            print(f"\n{GRN}✓ {sender_email} vitlistad. Nästa poll-cykel skickar svar automatiskt.{NRM}")
        else:
            print(f"{GRY}Kunde inte lägga till i vitlistan.{NRM}")

    elif action == "S":
        now = __import__("datetime").datetime.utcnow().isoformat()
        try:
            con.execute(
                "INSERT OR IGNORE INTO blacklist (email, added_at) VALUES (?, ?)",
                (sender_email, now)
            )
            con.execute(
                "UPDATE mail SET status = 'FLAGGED', updated_at = ? "
                "WHERE status = 'WAITING' AND sender LIKE ?",
                (now, f"%{sender_email}%")
            )
            con.commit()
            print(f"\n{GRN}✓ {sender_email} svartlistad. Väntande mail stängda.{NRM}")
        except Exception as e:
            print(f"{GRY}Fel: {e}{NRM}")

    elif action == "B":
        now = __import__("datetime").datetime.utcnow().isoformat()
        try:
            con.execute(
                "UPDATE mail SET status = 'FLAGGED', updated_at = ? "
                "WHERE status = 'WAITING' AND sender LIKE ?",
                (now, f"%{sender_email}%")
            )
            con.commit()
            print(f"\n{GRN}✓ {sender_email} behålls olistad. Inga fler åtgärder.{NRM}")
        except Exception as e:
            print(f"{GRY}Fel: {e}{NRM}")

    con.close()
    menu_pause()


def _mail_admin(tool: dict, state: dict) -> None:
    """Startar behörighetsadmin TUI för clio-agent-mail."""
    script_dir = tool["script"].parent
    admin_script = script_dir / "admin.py"
    if not admin_script.exists():
        print(f"\n{GRY}admin.py hittades inte: {admin_script}{NRM}")
        menu_pause()
        return

    for env_file in (script_dir.parent / ".env", script_dir / ".env"):
        if env_file.exists():
            try:
                from dotenv import load_dotenv as _ld
                _ld(env_file, override=False)
            except ImportError:
                pass

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("admin", str(admin_script))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
    except KeyboardInterrupt:
        print(f"\n{GRY}(Avbruten){NRM}")
    except Exception as e:
        print(f"\n{GRY}Fel: {e}{NRM}")
    menu_pause()


def _mail_insights(tool: dict, state: dict) -> None:
    """Kör insiktsanalys och visar resultatet i TUI."""
    script_dir = tool["script"].parent
    cfg_path = script_dir / "clio.config"
    if not cfg_path.exists():
        print(f"\n{GRY}clio.config hittades inte.{NRM}")
        menu_pause()
        return

    cfg = configparser.ConfigParser()
    cfg.read(str(cfg_path), encoding="utf-8")

    for env_file in (script_dir.parent / ".env", script_dir / ".env"):
        if env_file.exists():
            try:
                from dotenv import load_dotenv as _ld
                _ld(env_file, override=False)
            except ImportError:
                pass

    cmd = [
        sys.executable, "-c",
        (
            "import sys; sys.path.insert(0, r'" + str(script_dir) + "'); "
            "import configparser, os; "
            "from dotenv import load_dotenv; "
            f"load_dotenv(r'{script_dir.parent / '.env'}'); "
            f"load_dotenv(r'{script_dir / '.env'}', override=True); "
            "cfg = configparser.ConfigParser(); "
            f"cfg.read(r'{cfg_path}', encoding='utf-8'); "
            "import insights; "
            "print(insights.run_insights(cfg))"
        )
    ]

    print(f"\n{BLD}Insiktsanalys startar...{NRM}")
    print(f"{'─' * 56}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                cwd=str(script_dir))
        output = result.stdout.strip()
        if output:
            print(output)
        if result.stderr.strip():
            print(f"\n{GRY}{result.stderr.strip()[:500]}{NRM}")
    except Exception as e:
        print(f"{GRY}Fel: {e}{NRM}")
    print(f"{'─' * 56}")
    menu_pause()


# ── Launcher ──────────────────────────────────────────────────────────────────

def run_mail(tool: dict, state: dict) -> None:
    """Custom launcher för clio-agent-mail."""
    if not tool["script"].exists():
        print(f"\nScript saknas: {tool['script']}")
        menu_pause()
        return

    _MAIL_CHOICES = [
        "1. Starta daemon      (pollar kontinuerligt var 5 min)",
        "2. Kör ett pass nu    (--once, avslutar efteråt)",
        "3. Dry-run            (--dry-run, skickar inget)",
        "4. Vitlista           (lägg till adress i Notion)",
        "5. Maillogg           (senaste hanterade mail)",
        "6. Insiktsanalys      (analysera mönster + förutsäg frågor)",
        "7. Behörighetsadmin   (hantera kodord-scope per användare)",
    ]

    choice = menu_select("clio-agent-mail:", _MAIL_CHOICES)
    if choice is None:
        return
    mode = choice[0]

    if mode == "4":
        _mail_whitelist(tool, state)
        return
    if mode == "5":
        _mail_log(tool, state)
        return
    if mode == "6":
        _mail_insights(tool, state)
        return
    if mode == "7":
        _mail_admin(tool, state)
        return

    cmd = [sys.executable, str(tool["script"])]
    label = ""

    if mode == "1":
        label = "daemon"
    elif mode == "2":
        cmd.append("--once")
        label = "ett pass"
    elif mode == "3":
        cmd += ["--dry-run", "--once"]
        label = "dry-run"
    else:
        return

    state["last_run"] = tool["name"]
    save_state(state)

    print(f"\nStartar clio-agent-mail ({label})...")
    print("─" * 40)
    start = datetime.now()
    try:
        subprocess.run(cmd, text=True, errors="replace")
    except KeyboardInterrupt:
        print("\n(Avbruten av användaren)")
    except Exception as e:
        print(f"\nFel vid körning: {e}")
    elapsed = (datetime.now() - start).seconds
    print(f"\n{'─' * 40}")
    print(t("run_done", s=elapsed))
    menu_pause()
