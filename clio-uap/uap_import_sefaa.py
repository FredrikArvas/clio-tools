"""
uap_import_sefaa.py — Importerar SEFAA (f.d. CEFAA) utredningsfall till uap.report

Källa: https://sefaa.dgac.gob.cl (Sección de Estudios de Fenómenos Aéreos Anómalos, Chile)
Data: Officiella utredda fall 2018–nu, publicerade månadsvis.
Struktur: tag/casos-{year}/ → Casos {Mes} {Año} → PDF-länk per fall

Från PDF-filnamnet extraheras:
  CASO-N°-{num}-{DDMMYYYY}.pdf  →  case_number + observation_date

PDF-filer sparas i: ~/19.0/clio-tools/clio-uap/sefaa_pdfs/
Text extraheras med pdfplumber och lagras som raw_description.

Kör: python3 uap_import_sefaa.py [--dry-run] [--years 2024 2025]
     python3 uap_import_sefaa.py --update-descriptions   (uppdatera befintliga med PDF-text)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import xmlrpc.client
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = os.getenv("ODOO_DB", "uap")
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

BASE_URL  = "https://sefaa.dgac.gob.cl"
ALL_YEARS = list(range(2018, datetime.now().year + 1))
UA = "clio-uap/1.0 (SEFAA importer)"

PDF_DIR = Path(__file__).parent / "sefaa_pdfs"
PDF_DIR.mkdir(exist_ok=True)

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
# PDF
# ---------------------------------------------------------------------------

def download_pdf(pdf_url: str, case_num: str) -> Path | None:
    """Ladda ner PDF om den inte redan finns. Returnerar lokal sökväg."""
    fname = urllib.parse.unquote(pdf_url.rsplit("/", 1)[-1])
    # Sanera filnamn
    safe = re.sub(r'[^\w\-.]', '_', fname)
    dest = PDF_DIR / safe
    if dest.exists():
        return dest
    # Säkerställ att URL:en är ASCII-säker (koda icke-ASCII-tecken)
    parsed = urllib.parse.urlsplit(pdf_url)
    safe_path = urllib.parse.quote(parsed.path, safe='/:@!$&\'()*+,;=')
    safe_url = urllib.parse.urlunsplit(parsed._replace(path=safe_path))
    try:
        req = urllib.request.Request(safe_url, headers={"User-Agent": UA, "Referer": BASE_URL})
        with urllib.request.urlopen(req, timeout=30) as r:
            dest.write_bytes(r.read())
        return dest
    except Exception as e:
        print(f"  FEL nedladdning {case_num}: {e}")
        return None


def extract_text(pdf_path: Path) -> str:
    """Extrahera text ur PDF med pdfplumber. Returnerar tom sträng vid fel."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t.strip())
        return "\n\n".join(text_parts)[:8000]  # max 8 000 tecken
    except Exception as e:
        return ""


# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE_URL})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_obs_date(ddmmyyyy: str) -> str | None:
    m = re.match(r"(\d{2})(\d{2})(\d{4})", ddmmyyyy)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, min(d, 28), 12, 0).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def extract_monthly_urls(year_tag_html: str) -> list[str]:
    return list(dict.fromkeys(
        re.findall(
            r'href=["\'](' + re.escape(BASE_URL) + r'/\d{4}/\d{2}/\d{2}/casos-[a-z]+-\d{4}/?)["\']',
            year_tag_html
        )
    ))


def extract_cases(monthly_html: str) -> list[dict]:
    seen = set()
    cases = []
    for pdf_url in re.findall(
        r'href=["\'](' + re.escape(BASE_URL) + r'/wp-content/uploads/[^"\']+CASO[^"\']+\.pdf)["\']',
        monthly_html
    ):
        decoded = urllib.parse.unquote(pdf_url)
        fname   = decoded.rsplit("/", 1)[-1]
        m = re.search(r"CASO-N[°o]?-(\d+(?:-\d+)?)-(\d{8})\.pdf", fname, re.IGNORECASE)
        if not m:
            continue
        case_num = m.group(1)
        date_str = m.group(2)
        if case_num in seen:
            continue
        seen.add(case_num)
        cases.append({"case_num": case_num, "date": date_str, "pdf_url": pdf_url})
    return cases


# ---------------------------------------------------------------------------
# Uppdatera befintliga poster med PDF-text
# ---------------------------------------------------------------------------

def update_descriptions():
    """Hämta befintliga poster vars raw_description bara är en URL, ladda ner PDF och extrahera text."""
    print("\nUppdaterar befintliga poster med PDF-text...")
    records = kw("uap.report", "search_read",
        [[["database_id", "=", 37], ["raw_description", "=like", "Rapport PDF:%"]]],
        {"fields": ["id", "external_id", "raw_description"]}
    )
    print(f"  Poster att uppdatera: {len(records)}")
    updated = failed = skipped = 0
    for rec in records:
        pdf_url = rec["raw_description"].replace("Rapport PDF: ", "").strip()
        case_num = rec["external_id"].replace("SEFAA-", "")
        pdf_path = download_pdf(pdf_url, case_num)
        if not pdf_path:
            failed += 1
            continue
        text = extract_text(pdf_path)
        if not text:
            skipped += 1
            continue
        try:
            kw("uap.report", "write", [[rec["id"]], {"raw_description": text}])
            updated += 1
            if updated % 20 == 0:
                print(f"  ... {updated} uppdaterade")
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  FEL {rec['external_id']}: {e}")
        time.sleep(0.1)
    print(f"\n  Uppdaterade: {updated} | Inga PDF-text: {skipped} | Fel: {failed}")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def run(dry_run: bool, years: list[int], save_pdfs: bool):
    print(f"\n{'─'*60}")
    print("  SEFAA (f.d. CEFAA) importer")
    print(f"{'─'*60}")
    if dry_run:
        print("  *** DRY RUN ***")
    print(f"  År: {years}")
    print(f"  PDF-katalog: {PDF_DIR}")

    existing = {r["external_id"] for r in kw("uap.report", "search_read",
        [[["external_id", "=like", "SEFAA-%"]]], {"fields": ["external_id"]})
        if r.get("external_id")}
    print(f"  Redan importerade: {len(existing)}")

    cl = kw("res.country", "search_read", [[["code", "=", "CL"]]], {"fields": ["id"]})
    cl_id = cl[0]["id"] if cl else False

    db_name = "SEFAA — Sección de Estudios de Fenómenos Aéreos Anómalos (Chile)"
    existing_dbs = kw("uap.database", "search_read", [[["name", "=", db_name]]], {"fields": ["id"]})
    if existing_dbs:
        db_id = existing_dbs[0]["id"]
    elif not dry_run:
        db_id = kw("uap.database", "create", [{"name": db_name}])
        print(f"  [NY DB] {db_name} → id={db_id}")
    else:
        db_id = 0

    created = skipped = errors = 0
    all_cases: list[dict] = []

    for year in years:
        tag_url = f"{BASE_URL}/tag/casos-{year}/"
        print(f"  Hämtar {tag_url} ...")
        try:
            tag_html = fetch(tag_url)
        except Exception as e:
            print(f"  FEL (tag {year}): {e}")
            continue
        monthly_urls = extract_monthly_urls(tag_html)
        print(f"  {year}: {len(monthly_urls)} månadssidor")
        for murl in monthly_urls:
            try:
                mhtml = fetch(murl)
                cases = extract_cases(mhtml)
                for c in cases:
                    c["year"] = year
                all_cases.extend(cases)
                time.sleep(0.2)
            except Exception as e:
                print(f"  FEL ({murl}): {e}")

    print(f"\n  Totalt fall insamlade: {len(all_cases)}")
    new_cases = [c for c in all_cases if f"SEFAA-{c['case_num']}" not in existing]
    print(f"  Nya (ej i DB): {len(new_cases)}")

    for case in new_cases:
        ext_id = f"SEFAA-{case['case_num']}"
        report_date = parse_obs_date(case["date"])

        # Ladda ner PDF och extrahera text
        raw_desc = f"Rapport PDF: {case['pdf_url']}"
        if save_pdfs and not dry_run:
            pdf_path = download_pdf(case["pdf_url"], case["case_num"])
            if pdf_path:
                text = extract_text(pdf_path)
                if text:
                    raw_desc = text
            time.sleep(0.3)

        vals = {
            "external_id":     ext_id,
            "raw_title":       f"SEFAA Caso N° {case['case_num']}",
            "report_date":     report_date or False,
            "country_id":      cl_id or False,
            "shape":           False,
            "status":          "unlinked",
            "database_id":     db_id or False,
            "reporter_type":   "official",
            "raw_description": raw_desc,
        }

        if dry_run:
            if created < 8:
                print(f"  [DRY] {ext_id} | {report_date} | {case['pdf_url'].rsplit('/',1)[-1][:50]}")
            created += 1
            existing.add(ext_id)
            continue

        try:
            kw("uap.report", "create", [vals])
            created += 1
            existing.add(ext_id)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  FEL {ext_id}: {str(e)[:120]}")

    print(f"\n  Skapade  : {created}")
    print(f"  Hoppade  : {skipped}")
    print(f"  Fel      : {errors}")
    if save_pdfs:
        pdf_count = len(list(PDF_DIR.glob("*.pdf")))
        print(f"  PDFs i {PDF_DIR.name}/: {pdf_count}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--years", nargs="+", type=int, default=ALL_YEARS)
    ap.add_argument("--no-pdfs", action="store_true", help="Skippa PDF-nedladdning")
    ap.add_argument("--update-descriptions", action="store_true",
                    help="Uppdatera befintliga poster (URL→PDF-text)")
    args = ap.parse_args()

    if args.update_descriptions:
        update_descriptions()
    else:
        run(args.dry_run, args.years, save_pdfs=not args.no_pdfs)
