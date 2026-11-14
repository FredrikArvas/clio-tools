"""
uap_import_cobeps.py — Importerar COBEPS-utredningsrapporter till uap.report

Källa: https://www.cobeps.org/fr/database
Data: ~43 utredda belgiska fall, 1987–2025.
Kolumner: titel | PAN (A–D) | Hynek | datum | plats | popup-URL

PAN-klassificering:
  A = Identifié (förklarat)
  B = Probablement identifié
  C = Insuffisamment documenté
  D = Non identifié (oförklarat)

Kör: python3 uap_import_cobeps.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.request
import xmlrpc.client
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)
# Modulens .env pekar på uap-databasen och ska vinna över rotens ODOO_URL (aiab)
load_dotenv(Path(__file__).parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = os.getenv("ODOO_DB", "uap")
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

BASE_URL   = "https://www.cobeps.org"
DB_URL     = f"{BASE_URL}/fr/database"
UA = "clio-uap/1.0 (COBEPS importer)"

# ---------------------------------------------------------------------------
# Odoo
# ---------------------------------------------------------------------------
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
UID    = common.authenticate(DB, USER, PWD, {})
if not UID:
    sys.exit("Odoo-autentisering misslyckades")
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, kwargs=None):
    return M.execute_kw(DB, UID, PWD, model, method, args, kwargs or {})


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE_URL})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    # Avkoda vanliga HTML-entiteter
    text = text.replace("&nbsp;", "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
    return text.strip()


def parse_date(ddmmyyyy: str) -> str | None:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", ddmmyyyy.strip())
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, min(d, 28), 12, 0).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", s).strip("-")[:40]


def fetch_popup_description(popup_url: str) -> str:
    try:
        html = fetch(popup_url)
        # Ta bort nav/header/footer
        body_m = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
        body = body_m.group(1) if body_m else html
        # Rensa taggar och blankrader
        text = strip_tags(body)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # Hoppa över titeln (rad 1) och "Fermer la fenêtre"/"COBEPS"-rader
        desc_lines = [
            l for l in lines
            if not re.match(r"(Fermer|COBEPS association|Cliquez|Dernière)", l, re.I)
            and len(l) > 10
        ]
        return " ".join(desc_lines[1:4])  # Ta max 3 informationsrader
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Parsning av HTML-tabell
# ---------------------------------------------------------------------------

def extract_rows(html: str) -> list[dict]:
    rows = []
    # Hitta alla TR i tabellen
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
        cells_raw = re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.DOTALL | re.IGNORECASE)
        if len(cells_raw) < 4:
            continue
        cells = [strip_tags(c) for c in cells_raw]

        # Extrahera länkar
        title_a = re.search(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', cells_raw[0], re.I)
        info_a  = re.search(r'href=["\']([^"\']+)["\']', cells_raw[-1], re.I)

        pdf_url   = title_a.group(1) if title_a else ""
        popup_url = info_a.group(1) if info_a else ""

        # Gör relativa URL:er absoluta
        if pdf_url and not pdf_url.startswith("http"):
            pdf_url = BASE_URL + "/" + pdf_url.lstrip("./")
        if popup_url and not popup_url.startswith("http"):
            popup_url = BASE_URL + "/" + popup_url.lstrip("./")

        # Hitta datum-cellen (DD/MM/YYYY)
        date_str = loc = pan = hynek = ""
        for i, c in enumerate(cells):
            if re.match(r"\d{1,2}/\d{1,2}/\d{4}", c):
                date_str = c
                loc      = cells[i + 1] if i + 1 < len(cells) else ""
                # PAN och Hynek sitter före datum
                # Kolumnordning: titel [PAN] [Hynek] datum plats info
                pre = [cells[j] for j in range(1, i) if cells[j]]
                pan   = pre[0] if len(pre) > 0 else ""
                hynek = pre[1] if len(pre) > 1 else ""
                break

        if not date_str:
            continue

        rows.append({
            "title":     cells[0],
            "pan":       pan,
            "hynek":     hynek,
            "date":      date_str,
            "location":  loc,
            "pdf_url":   pdf_url,
            "popup_url": popup_url,
        })
    return rows


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def run(dry_run: bool, limit: int | None = None):
    print(f"\n{'─'*60}")
    print("  COBEPS importer")
    print(f"{'─'*60}")
    if dry_run:
        print("  *** DRY RUN ***")

    print(f"  Hämtar {DB_URL} ...")
    html = fetch(DB_URL)
    print(f"  HTML: {len(html):,} bytes")

    rows = extract_rows(html)
    print(f"  Rader parsade: {len(rows)}")

    # Befintliga external_ids — =like för exakt prefix-match (LIKE 'COBEPS-%')
    existing = {r["external_id"] for r in kw("uap.report", "search_read",
        [[["external_id", "=like", "COBEPS-%"]]], {"fields": ["external_id"]})
        if r.get("external_id")}
    print(f"  Redan importerade: {len(existing)}")

    # Belgiens country_id
    be = kw("res.country", "search_read", [[["code", "=", "BE"]]], {"fields": ["id"]})
    be_id = be[0]["id"] if be else False

    # COBEPS-databas
    db_name = "COBEPS — Comité Belge d'Étude des Phénomènes Spatiaux"
    existing_dbs = kw("uap.database", "search_read",
                       [[["name", "=", db_name]]], {"fields": ["id"]})
    if existing_dbs:
        db_id = existing_dbs[0]["id"]
    elif not dry_run:
        db_id = kw("uap.database", "create", [{"name": db_name}])
        print(f"  [NY DB] {db_name} → id={db_id}")
    else:
        db_id = 0

    created = skipped = errors = 0
    t0 = time.time()

    for row in rows:
        slug   = slugify(row["title"])
        date_m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", row["date"])
        yyyymmdd = f"{date_m.group(3)}{int(date_m.group(2)):02d}{int(date_m.group(1)):02d}" if date_m else "00000000"
        ext_id = f"COBEPS-{yyyymmdd}-{slug}"

        if ext_id in existing:
            skipped += 1
            continue
        if limit and (created + errors) >= limit:
            break

        report_date = parse_date(row["date"])

        # Popup-beskrivning (ej vid dry-run för att spara tid)
        desc = ""
        if not dry_run and row["popup_url"]:
            desc = fetch_popup_description(row["popup_url"])
            time.sleep(0.3)  # artig paus

        pan_label = {"A": "PAN A — Identifié", "B": "PAN B — Probablement identifié",
                     "C": "PAN C — Insuffisamment documenté", "D": "PAN D — Non identifié"
                     }.get(row["pan"], f"PAN {row['pan']}" if row["pan"] else "")

        raw_desc_parts = [p for p in [pan_label, desc] if p]
        if row["pdf_url"]:
            raw_desc_parts.append(f"Rapport PDF: {row['pdf_url']}")
        raw_description = "\n".join(raw_desc_parts) or False

        vals = {
            "external_id":    ext_id,
            "raw_title":      row["title"],
            "report_date":    report_date or False,
            "country_id":     be_id or False,
            "location_text":  row["location"] or False,
            "shape":          row["hynek"] or False,
            "status":         "unlinked",
            "database_id":    db_id or False,
            "reporter_type":  "civilian",
            "raw_description": raw_description,
        }

        if dry_run:
            print(f"  [DRY] {ext_id}")
            print(f"        PAN={row['pan']} Hynek={row['hynek']} Plats={row['location']}")
            created += 1
            existing.add(ext_id)
            continue

        try:
            kw("uap.report", "create", [vals])
            created += 1
            existing.add(ext_id)
            print(f"  ✓ {ext_id}")
        except Exception as e:
            errors += 1
            print(f"  FEL {ext_id}: {str(e)[:120]}")

    elapsed = time.time() - t0
    print(f"\n  Skapade  : {created}")
    print(f"  Hoppade  : {skipped}")
    print(f"  Fel      : {errors}")
    print(f"  Tid      : {elapsed:.1f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit",   type=int, default=None,
                    help="Max nya poster (för test)")
    args = ap.parse_args()
    run(args.dry_run, args.limit)
