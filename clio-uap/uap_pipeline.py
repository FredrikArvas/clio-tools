"""
uap_pipeline.py — Stage 3 + 4: Kluster → Encounter → Serie

Stage 3 (cluster):
  Grupperar uap.report (status=unlinked) till uap.encounter via
  haversine-avstånd + datum-fönster. Varje rapport som inte matchar
  någon annan skapar ändå ett eget encounter (singleton).

Stage 4 (series):
  Söker mönster bland encounters utan series_id. Skapar uap.series
  för kluster med ≥ SERIES_MIN_ENCOUNTERS inom SERIES_RADIUS_KM / SERIES_DAYS.

Kör: python3 uap_pipeline.py [--stage all|cluster|series] [--dry-run]
"""
from __future__ import annotations
import argparse, hashlib, math, os, sys, time, xmlrpc.client
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

URL  = os.getenv("ODOO_URL", "http://localhost:8069")
DB   = "uapdb"
USER = os.getenv("ODOO_USER", "")
PWD  = os.getenv("ODOO_PASSWORD", "")

# ── Kluster-parametrar ──────────────────────────────────────────────────────
ENCOUNTER_RADIUS_KM = 50    # rapporter inom 50 km …
ENCOUNTER_DAYS      = 3     # … och 3 dagar = samma encounter

# ── Serie-parametrar ────────────────────────────────────────────────────────
SERIES_RADIUS_KM          = 200   # encounters inom 200 km …
SERIES_DAYS               = 90    # … och 90 dagar = kandidat-serie
SERIES_MIN_ENCOUNTERS     = 3     # minst 3 encounters → serie
SERIES_AUTO_CONFIRM_COUNT = 10    # ≥ 10 encounters → auto_confirmed

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
# Geometri
# ---------------------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Avstånd i km mellan två koordinater (Haversine-formeln)."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


def centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Geografisk centroid (lat, lon) för en lista punkter."""
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    return round(lat, 6), round(lon, 6)


def bbox_radius(points: list[tuple[float, float]]) -> float:
    """Ungefärlig radie (km) för en punktmängd."""
    if len(points) < 2:
        return 0.0
    clat, clon = centroid(points)
    return max(haversine(clat, clon, p[0], p[1]) for p in points)


# ---------------------------------------------------------------------------
# Stage 3 — Kluster rapporter → encounters
# ---------------------------------------------------------------------------

def stage_cluster(dry_run: bool):
    print(f"\n{'─'*60}")
    print("  STAGE 3 — Kluster rapporter → encounters")
    print(f"{'─'*60}")
    print(f"  Parametrar: {ENCOUNTER_RADIUS_KM} km / {ENCOUNTER_DAYS} dagar")

    # Hämta obearbetade rapporter
    reports = kw("uap.report", "search_read",
                 [[["status", "=", "unlinked"],
                   ["geo_lat", "!=", 0.0],
                   ["geo_lng", "!=", 0.0]]],
                 {"fields": ["id", "raw_title", "report_date", "geo_lat", "geo_lng",
                             "country_id", "location_text", "database_id",
                             "shape", "duration_text", "external_id"],
                  "limit": 50_000})

    print(f"  Obearbetade rapporter: {len(reports)}")
    if not reports:
        print("  Inget att klustrera.")
        return

    # Parsa datum till datetime-objekt för jämförelse
    def parse_dt(s: str) -> datetime | None:
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    for r in reports:
        r["_dt"] = parse_dt(r.get("report_date") or "")

    # Sortera på datum (None sist)
    reports.sort(key=lambda r: r["_dt"] or datetime.max)

    # DBSCAN-liknande klustring: O(n²) — OK upp till ~5 000 rapporter
    assigned   = [False] * len(reports)
    clusters   = []

    for i, rpt in enumerate(reports):
        if assigned[i]:
            continue
        cluster = [i]
        assigned[i] = True

        if rpt["_dt"] is None or rpt["geo_lat"] == 0.0:
            clusters.append(cluster)
            continue

        for j in range(i + 1, len(reports)):
            if assigned[j]:
                continue
            other = reports[j]
            if other["_dt"] is None or other["geo_lat"] == 0.0:
                continue
            # Datum-check (snabb) före avstånd (dyrare)
            if abs((other["_dt"] - rpt["_dt"]).days) > ENCOUNTER_DAYS:
                # Eftersom listan är datums-sorterad kan vi bryta här
                break
            if haversine(rpt["geo_lat"], rpt["geo_lng"],
                         other["geo_lat"], other["geo_lng"]) <= ENCOUNTER_RADIUS_KM:
                cluster.append(j)
                assigned[j] = True

        clusters.append(cluster)

    print(f"  Kluster bildade: {len(clusters)} "
          f"({sum(1 for c in clusters if len(c) > 1)} med ≥ 2 rapporter)")

    # Hämta befintliga encounter_ids för att undvika dubbletter
    existing_enc_ids = set(
        r["encounter_id"]
        for r in kw("uap.encounter", "search_read", [[]], {"fields": ["encounter_id"]})
    )

    # Hämta landsmap (Odoo country id → ISO-kod)
    countries = kw("res.country", "search_read", [[]], {"fields": ["id", "code"]})
    country_code = {c["id"]: c["code"] for c in countries}

    created_enc = linked_rpts = skipped = 0
    t0 = time.time()

    for cluster_idx, cluster in enumerate(clusters):
        recs = [reports[i] for i in cluster]

        # --- Beräkna encounter-egenskaper ---
        coords   = [(r["geo_lat"], r["geo_lng"]) for r in recs if r["geo_lat"] != 0.0]
        clat, clon = centroid(coords) if coords else (0.0, 0.0)

        dates    = [r["_dt"] for r in recs if r["_dt"]]
        date_obs = min(dates).strftime("%Y-%m-%d 12:00:00") if dates else False
        year     = min(dates).year if dates else 0

        # Land: majoritetsval
        country_ids = [r["country_id"][0] for r in recs if r.get("country_id")]
        cid = max(set(country_ids), key=country_ids.count) if country_ids else False
        cc  = country_code.get(cid, "XX") if cid else "XX"

        # Titel: längsta råtitel i klustret
        title = max((r["raw_title"] or "" for r in recs), key=len) or "UFO Sighting"

        # Databas
        db_ids = [r["database_id"][0] for r in recs if r.get("database_id")]
        db_id  = db_ids[0] if db_ids else False

        # Generera encounter_id
        hash_input = f"{cc}_{year}_{recs[0].get('external_id','')}"
        enc_hash   = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        enc_id     = f"NUFORC_{cc}_{year}_{enc_hash}"

        if enc_id in existing_enc_ids:
            skipped += 1
            continue

        # Plats: vanligaste location_text
        locations = [r["location_text"] for r in recs if r.get("location_text")]
        location  = max(set(locations), key=locations.count) if locations else False

        enc_vals = {
            "encounter_id":  enc_id,
            "title_en":      title,
            "date_observed": date_obs,
            "country_id":    cid,
            "location":      location,
            "geo_lat":       clat,
            "geo_lng":       clon,
            "database_id":   db_id,
            "status":        "pending",
        }

        if dry_run:
            if created_enc < 5:
                print(f"  [DRY] {enc_id} | {title[:50]} | {len(recs)} rapporter")
            created_enc += 1
            linked_rpts += len(recs)
        else:
            try:
                new_enc_id = kw("uap.encounter", "create", [enc_vals])
                existing_enc_ids.add(enc_id)
                created_enc += 1

                # Länka rapporterna till encounter
                report_ids = [r["id"] for r in recs]
                kw("uap.report", "write",
                   [report_ids, {"encounter_id": new_enc_id, "status": "linked"}])
                linked_rpts += len(recs)
            except Exception as e:
                print(f"  FEL {enc_id}: {e}")

        if (cluster_idx + 1) % 100 == 0:
            print(f"  [{cluster_idx+1}/{len(clusters)}] "
                  f"skapade={created_enc} länkade={linked_rpts}")

    elapsed = time.time() - t0
    print(f"\n  Encounters skapade : {created_enc}")
    print(f"  Rapporter länkade  : {linked_rpts}")
    print(f"  Skippade (finns)   : {skipped}")
    print(f"  Tid                : {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# Stage 4 — Detektera serier från encounters
# ---------------------------------------------------------------------------

def classify_series_type(enc_count: int, bbox: float, date_range_days: int) -> str:
    if bbox < 50 and enc_count >= 5:
        return "swarm"
    if date_range_days > 60 and enc_count >= 5:
        return "recurring"
    if bbox >= 100:
        return "wave"
    if date_range_days <= 14 and bbox < 100:
        return "single_extended"
    return "wave"


def stage_series(dry_run: bool):
    print(f"\n{'─'*60}")
    print("  STAGE 4 — Seriedetektering")
    print(f"{'─'*60}")
    print(f"  Parametrar: {SERIES_RADIUS_KM} km / {SERIES_DAYS} dagar / "
          f"min {SERIES_MIN_ENCOUNTERS} encounters")

    # Hämta encounters utan series_id, med koordinater
    encounters = kw("uap.encounter", "search_read",
                    [[["series_id", "=", False],
                      ["geo_lat", "!=", 0.0],
                      ["geo_lng", "!=", 0.0]]],
                    {"fields": ["id", "title_en", "date_observed",
                                "geo_lat", "geo_lng", "country_id"],
                     "limit": 100_000})

    print(f"  Encounters utan serie: {len(encounters)}")
    if len(encounters) < SERIES_MIN_ENCOUNTERS:
        print("  För få encounters för seriedetektering.")
        return

    # Parsa datum
    def parse_date(s):
        try:
            return datetime.fromisoformat(str(s))
        except Exception:
            return None

    for e in encounters:
        e["_dt"] = parse_date(e.get("date_observed"))

    valid = [e for e in encounters if e["_dt"] and e["geo_lat"] != 0.0]
    valid.sort(key=lambda e: e["_dt"])
    print(f"  Med datum + koordinater: {len(valid)}")

    # Klustring av encounters → serie-kandidater
    assigned   = [False] * len(valid)
    candidates = []

    for i, enc in enumerate(valid):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True

        for j in range(i + 1, len(valid)):
            if assigned[j]:
                continue
            other = valid[j]
            if abs((other["_dt"] - enc["_dt"]).days) > SERIES_DAYS:
                break
            if haversine(enc["geo_lat"], enc["geo_lng"],
                         other["geo_lat"], other["geo_lng"]) <= SERIES_RADIUS_KM:
                group.append(j)
                assigned[j] = True

        if len(group) >= SERIES_MIN_ENCOUNTERS:
            candidates.append(group)

    print(f"  Serie-kandidater: {len(candidates)}")
    if not candidates:
        print("  Inga mönster hittades med nuvarande parametrar.")
        return

    created_series = 0
    t0 = time.time()

    for grp in candidates:
        recs  = [valid[i] for i in grp]
        coords = [(r["geo_lat"], r["geo_lng"]) for r in recs]
        dates  = [r["_dt"] for r in recs]

        clat, clon       = centroid(coords)
        bbox             = bbox_radius(coords)
        date_start       = min(dates).date()
        date_end         = max(dates).date()
        date_range_days  = (date_end - date_start).days
        enc_count        = len(recs)

        series_type  = classify_series_type(enc_count, bbox, date_range_days)
        confidence   = min(enc_count / SERIES_AUTO_CONFIRM_COUNT, 1.0)
        status       = "auto_confirmed" if enc_count >= SERIES_AUTO_CONFIRM_COUNT else "auto_pending"

        # Namnge serien
        country_ids = [r["country_id"][1] if r.get("country_id") else "" for r in recs]
        top_country = max(set(country_ids), key=country_ids.count) if country_ids else ""
        name = (f"UAP {series_type.replace('_',' ').title()} — "
                f"{top_country} {date_start.year}"
                + (f"–{date_end.year}" if date_end.year != date_start.year else ""))

        # Unika länder
        unique_country_ids = list({r["country_id"][0]
                                   for r in recs if r.get("country_id")})

        if dry_run:
            print(f"  [DRY] {name}")
            print(f"         {enc_count} encounters | bbox={bbox:.0f}km | "
                  f"{date_start}→{date_end} | type={series_type} | "
                  f"conf={confidence:.2f} | status={status}")
            created_series += 1
        else:
            series_vals = {
                "name":        name,
                "series_type": series_type,
                "date_start":  str(date_start),
                "date_end":    str(date_end),
                "geo_lat":     clat,
                "geo_lng":     clon,
                "bbox_km":     round(bbox, 1),
                "country_ids": [[6, 0, unique_country_ids]],
                "confidence":  round(confidence, 2),
                "status":      status,
                "notes":       (f"Auto-genererad av uap_pipeline.py\n"
                                f"Encounters: {enc_count} | Bbox: {bbox:.0f} km | "
                                f"Period: {date_range_days} dagar"),
            }
            try:
                sid = kw("uap.series", "create", [series_vals])
                # Länka encounters till serien
                enc_ids = [r["id"] for r in recs]
                kw("uap.encounter", "write", [enc_ids, {"series_id": sid}])
                created_series += 1
                print(f"  Serie: {name} → {enc_count} encounters (ID {sid})")
            except Exception as e:
                print(f"  FEL serie '{name}': {e}")

    elapsed = time.time() - t0
    print(f"\n  Serier skapade: {created_series}")
    print(f"  Tid           : {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage",   choices=["all", "cluster", "series"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        print("*** DRY RUN — inga poster skapas ***")

    t_total = time.time()

    if args.stage in ("all", "cluster"):
        stage_cluster(args.dry_run)

    if args.stage in ("all", "series"):
        stage_series(args.dry_run)

    print(f"\n  Total tid: {time.time() - t_total:.1f}s")
