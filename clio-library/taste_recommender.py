#!/usr/bin/env python3
"""
taste_recommender.py — Clio Smakrådgivare v0.3
================================================
Hämtar betyg och bokklassificering från Notion, bygger smakprofiler
per person och ber Claude rekommendera nästa bokklubbsbok.

Utan argument startar ett interaktivt läge (används av clio.py-menyn).

Användning:
  python taste_recommender.py                              # interaktivt läge
  python taste_recommender.py --list-users                 # visa alla användare
  python taste_recommender.py --members Alice Ulrika       # rekommendera
  python taste_recommender.py --members Alice Ulrika --find-shared
  python taste_recommender.py --members Alice Ulrika --test BOK-0042 BOK-0099
  python taste_recommender.py --members Alice Ulrika --auto-test

Miljövariabler (laddas automatiskt från .env i clio-tools/ eller clio-library/):
  NOTION_TOKEN      — secret_xxx
  ANTHROPIC_API_KEY — sk-ant-xxx

Databas-IDs:
  Bokregister:   94906f71-ee0f-4ff8-8c4b-28e822f6e670
  Betyg:         41009da8-a1e7-48e2-9ed9-7f3c9406ef93
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from pathlib import Path


def load_dotenv():
    """Letar efter .env uppåt i filträdet och laddar KEY=value till os.environ."""
    d = Path(__file__).resolve().parent
    for _ in range(5):           # max 5 nivåer uppåt
        env_file = d / ".env"
        if env_file.exists():
            with open(env_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if val and not os.environ.get(key):  # sätts om saknas eller tom
                        os.environ[key] = val
        d = d.parent


# ─── KONFIGURATION ────────────────────────────────────────────────────────────
NOTION_VERSION     = "2022-06-28"
NOTION_API         = "https://api.notion.com/v1"
ANTHROPIC_API      = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL    = "claude-sonnet-4-20250514"

BOKREGISTER_DB     = "94906f71-ee0f-4ff8-8c4b-28e822f6e670"
BETYG_DB           = "41009da8-a1e7-48e2-9ed9-7f3c9406ef93"

MIN_RATING         = 4   # betyg ≥ 4 räknas som "gillar"
MAX_RATING         = 2   # betyg ≤ 2 räknas som "gillar inte"


# ─── NOTION HELPERS ───────────────────────────────────────────────────────────
def notion_request(method, path, token, body=None):
    url  = f"{NOTION_API}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization":  f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type":   "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  ⚠️  Notion {e.code} på {path}: {body[:200]}", file=sys.stderr)
        return {}


def notion_query_all(token, db_id, filter_body=None):
    """Hämtar alla sidor ur en Notion-databas med pagination."""
    pages  = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if filter_body:
            body["filter"] = filter_body
        if cursor:
            body["start_cursor"] = cursor
        result = notion_request("POST", f"/databases/{db_id}/query", token, body)
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
        time.sleep(0.1)
    return pages


def prop_text(page, name):
    p = page.get("properties", {}).get(name, {})
    t = p.get("type")
    if t == "title":
        parts = p.get("title", [])
    elif t == "rich_text":
        parts = p.get("rich_text", [])
    else:
        return ""
    return "".join(x.get("plain_text", "") for x in parts).strip()


def prop_select(page, name):
    p = page.get("properties", {}).get(name, {})
    s = p.get("select") or {}
    return s.get("name", "")


def prop_multi_select(page, name):
    p = page.get("properties", {}).get(name, {})
    return [x.get("name", "") for x in p.get("multi_select", [])]


def prop_number(page, name):
    p = page.get("properties", {}).get(name, {})
    return p.get("number")


# ─── DATA-HÄMTNING ────────────────────────────────────────────────────────────
def fetch_ratings(token, members):
    """Hämtar alla betyg för angivna personer. Returnerar dict: person → list of {bok_id, betyg}"""
    print(f"  Hämtar betyg för: {', '.join(members)}...")
    all_pages = notion_query_all(token, BETYG_DB)
    print(f"  → {len(all_pages)} betygsposter totalt")

    ratings = defaultdict(list)
    for page in all_pages:
        person  = prop_select(page, "Person")
        bok_id  = prop_text(page, "BOK-ID")
        betyg   = prop_number(page, "Betyg")
        if person in members and bok_id and betyg is not None:
            ratings[person].append({"bok_id": bok_id, "betyg": betyg})

    for m in members:
        print(f"  → {m}: {len(ratings[m])} betyg")
    return ratings


def load_bokid_cache():
    """Laddar bokid_cache.json och bygger en omvänd lookup: titel||författare → BOK-ID."""
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bokid_cache.json")
    if not os.path.exists(cache_path):
        print(f"  ⚠️  bokid_cache.json saknas — kör match_bokid.py först")
        return {}
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)   # key: "titel||författare" → BOK-ID


def bokid_title_map():
    """Reverse-map ur cachen: BOK-XXXX → titel (title case). Fallback när boken saknas i books-dict."""
    result = {}
    for key, bok_id in load_bokid_cache().items():
        result[bok_id] = key.split("||")[0].title()
    return result


def fetch_books(token):
    """Hämtar alla böcker ur Bokregistret med klassificeringsfält."""
    print("  Hämtar Bokregistret...")
    all_pages = notion_query_all(token, BOKREGISTER_DB)
    print(f"  → {len(all_pages)} sidor i Notion")

    # Ladda BOK-ID-cache (titel||författare → BOK-XXXX)
    cache = load_bokid_cache()
    # Bygg omvänd lookup för snabb matchning
    # Cache-nycklar är lowercase: "titel||författare"

    books = {}
    matched = 0
    for page in all_pages:
        titel   = prop_text(page, "Titel")
        forfatt = prop_text(page, "Författare")

        if not titel:
            continue

        # Matcha via cache: titel||författare (lowercase)
        cache_key = f"{titel.lower()}||{forfatt.lower()}"
        bok_id = cache.get(cache_key)

        if not bok_id:
            # Prova utan författare (ibland saknas)
            for ck, bid in cache.items():
                if ck.startswith(f"{titel.lower()}||"):
                    bok_id = bid
                    break

        if not bok_id:
            continue

        matched += 1
        books[bok_id] = {
            "bok_id":   bok_id,
            "titel":    titel,
            "forfattare": forfatt,
            "sprak":    prop_select(page, "Språk"),
            "funktion": prop_select(page, "Funktion"),
            "varldsbild": prop_multi_select(page, "Världsbild"),
            "konceptuella": prop_text(page, "Konceptuella begrepp"),
            "primart_tema": prop_text(page, "Primärt tema"),
            "thema":    prop_text(page, "Thema"),
        }

    print(f"  → {matched} böcker matchade med BOK-ID (av {len(all_pages)} sidor)")
    return books


# ─── SMAKPROFIL ───────────────────────────────────────────────────────────────
def build_taste_profile(person, ratings_list, books):
    """
    Bygger en smakprofil per person baserat på högt- och lågtbetygsatta böcker.
    Returnerar en läsbar textsträng för Claude.
    """
    liked    = [r for r in ratings_list if r["betyg"] >= MIN_RATING]
    disliked = [r for r in ratings_list if r["betyg"] <= MAX_RATING]

    def summarize_books(rating_list, label):
        lines = []
        for r in rating_list:
            b = books.get(r["bok_id"])
            if not b:
                continue
            vb  = ", ".join(b["varldsbild"]) if b["varldsbild"] else "—"
            kon = b["konceptuella"] or "—"
            lines.append(
                f"  [{r['bok_id']}] {b['titel']} av {b['forfattare']} "
                f"(betyg {r['betyg']}) | Världsbild: {vb} | Begrepp: {kon}"
            )
        if not lines:
            return f"  (inga {label}böcker)"
        return "\n".join(lines[:40])  # max 40 rader per kategori

    profile = f"""
SMAKPROFIL: {person}
Gillar (betyg ≥ {MIN_RATING}, urval):
{summarize_books(liked, 'gillade ')}

Gillar inte (betyg ≤ {MAX_RATING}, urval):
{summarize_books(disliked, 'ogillad')}
""".strip()

    return profile, set(r["bok_id"] for r in ratings_list)


# ─── REKOMMENDATION VIA CLAUDE ────────────────────────────────────────────────
def recommend(api_key, members, ratings, books, blacklist=None):
    """Skickar smakprofiler + bokregister till Claude och ber om bokklubbsrekommendation."""
    blacklist = set(blacklist or [])

    # Bygg profiler
    profiles     = []
    all_read_ids = set()
    for member in members:
        profile_text, read_ids = build_taste_profile(member, ratings[member], books)
        profiles.append(profile_text)
        all_read_ids.update(read_ids)

    # Kandidatböcker = ej lästa av någon + ej svartlistade
    candidates = [
        b for bok_id, b in books.items()
        if bok_id not in all_read_ids and bok_id not in blacklist
    ]

    # Komprimera kandidatlistan för prompten
    cand_lines = []
    for b in candidates:
        vb  = ", ".join(b["varldsbild"]) if b["varldsbild"] else ""
        kon = b["konceptuella"] or ""
        cand_lines.append(
            f"[{b['bok_id']}] {b['titel']} | {b['forfattare']} | "
            f"Funktion: {b['funktion']} | Världsbild: {vb} | Begrepp: {kon} | "
            f"Tema: {b['primart_tema'] or ''}"
        )

    blacklist_note = ""
    if blacklist:
        bl_titles = [books[b]["titel"] for b in blacklist if b in books]
        blacklist_note = f"\nSVARTLISTADE (ska EJ föreslås): {', '.join(bl_titles or list(blacklist))}"

    prompt = f"""Du är Clio, smakrådgivare för Arvas Familjebibliotek.
Du ska rekommendera nästa bok för en bokklubb med: {', '.join(members)}.

MÅL: Hitta en bok som skapar bäst gemensamt samtal — inte nödvändigtvis allas favoritgenre,
utan den bok som engagerar hela gruppen och ger mest att prata om.
{blacklist_note}

{'=' * 60}
SMAKPROFILER
{'=' * 60}
{chr(10).join(profiles)}

{'=' * 60}
TILLGÄNGLIGA BÖCKER (ej lästa av någon i gruppen)
{'=' * 60}
{chr(10).join(cand_lines[:150])}

{'=' * 60}
UPPDRAG
{'=' * 60}
1. Identifiera smaköverlappet mellan personerna baserat på deras betygshistorik.
2. Välj ut 3 bokklubbskandidater från listan ovan.
3. För varje kandidat, skriv:
   - **[BOK-ID] Titel** av Författare
   - *Varför den passar gruppen* (1–2 meningar om gruppdynamiken)
   - *{members[0]}:* vad hen sannolikt uppskattar
   - *{members[1]}:* vad hen sannolikt uppskattar  
   - *Samtalspotential:* vad boken troligen väcker för diskussion

Svara på svenska. Var konkret och personlig — inte generisk."""

    print(f"\n  Skickar till Claude ({ANTHROPIC_MODEL})...")

    body = {
        "model":      ANTHROPIC_MODEL,
        "max_tokens": 1500,
        "messages":   [{"role": "user", "content": prompt}],
    }

    req = urllib.request.Request(
        ANTHROPIC_API,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type":    "application/json",
            "x-api-key":       api_key,
            "anthropic-version": "2023-06-01",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return data["content"][0]["text"]
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        return f"⚠️ Claude API-fel {e.code}: {err[:300]}"


# ─── TEST-LÄGE ────────────────────────────────────────────────────────────────
def find_shared_books(ratings, members, books, title_fallback=None):
    """Hittar böcker som alla i gruppen har betygsatt, delade in i gillar/tycker-olika."""
    sets = {}
    betyg_map = {}
    for member in members:
        sets[member]     = set()
        betyg_map[member] = {}
        for r in ratings[member]:
            sets[member].add(r["bok_id"])
            betyg_map[member][r["bok_id"]] = r["betyg"]

    shared = set.intersection(*sets.values()) if sets else set()

    both_like   = []
    differ      = []

    for bok_id in shared:
        betygs = [betyg_map[m].get(bok_id, 0) for m in members]
        titel  = books.get(bok_id, {}).get("titel")
        if not titel:
            titel = (title_fallback or {}).get(bok_id, bok_id)
        if all(b >= MIN_RATING for b in betygs):
            both_like.append((bok_id, titel, betygs))
        elif max(betygs) >= MIN_RATING and min(betygs) <= MAX_RATING:
            differ.append((bok_id, titel, betygs))

    return both_like, differ


def run_test_suite(notion_token, api_key, members, ratings, books, test_ids):
    """Kör tre scenarion och rapporterar."""
    bok_a, bok_b = test_ids[0], test_ids[1]
    titel_a = books.get(bok_a, {}).get("titel", bok_a)
    titel_b = books.get(bok_b, {}).get("titel", bok_b)

    scenarios = [
        ("BASLINJE (ingen svartlista)", []),
        (f"SVARTLISTA: '{titel_a}' (båda gillar)", [bok_a]),
        (f"SVARTLISTA: '{titel_b}' (delade meningar)", [bok_b]),
    ]

    sep = "=" * 70
    for i, (label, blacklist) in enumerate(scenarios):
        if i > 0:
            print("  ⏳ Väntar 90 s för att inte överskrida rate limit...")
            time.sleep(90)
        print(f"\n{sep}")
        print(f"  SCENARIO: {label}")
        print(sep)
        result = recommend(api_key, members, ratings, books, blacklist)
        print(result)
        print()


def fetch_users(token):
    """Hämtar alla unika Person-värden ur Betygstabellen med antal betyg."""
    from collections import Counter
    all_pages = notion_query_all(token, BETYG_DB)
    counts = Counter()
    for page in all_pages:
        p = page.get("properties", {}).get("Person", {})
        name = (p.get("select") or {}).get("name", "")
        if name:
            counts[name] += 1
    return sorted(counts.items(), key=lambda x: -x[1])   # [(namn, antal), ...]


def interactive_mode(notion_token, api_key):
    """Interaktivt läge — används när scriptet körs utan argument (t.ex. från clio.py)."""
    GRN = "\033[92m"; YEL = "\033[93m"; BLD = "\033[1m"; NRM = "\033[0m"

    print(f"\n{BLD}{'─' * 50}{NRM}")
    print(f"{BLD}  Clio Smakrådgivare{NRM}")
    print(f"{BLD}{'─' * 50}{NRM}")
    print("  Rekommenderar nästa bokklubbsbok via Notion + Claude.\n")

    # Hämta och visa användare
    print("  Hämtar användare från Notion...")
    users = fetch_users(notion_token)
    if not users:
        print("  ⚠️  Inga användare hittades i Betygstabellen.")
        return

    print(f"\n  {BLD}Registrerade läsare:{NRM}")
    for i, (name, count) in enumerate(users, 1):
        print(f"    {GRN}{i}.{NRM} {name} ({count} betyg)")

    print(f"\n  Ange siffror för de läsare du vill ha rekommendation för.")
    print(f"  Exempel: {YEL}1 3{NRM}  eller  {YEL}Alice Ulrika{NRM}")
    raw = input("\n  Välj läsare: ").strip()
    if not raw:
        print("  Avbruten.")
        return

    # Tolka inmatning — siffror eller namn
    members = []
    name_map = {str(i): name for i, (name, _) in enumerate(users, 1)}
    for token_val in raw.split():
        if token_val in name_map:
            members.append(name_map[token_val])
        else:
            members.append(token_val)  # antog att det är ett namn direkt

    if len(members) < 2:
        print("  ⚠️  Ange minst 2 läsare för en bokklubbsrekommendation.")
        return

    print(f"\n  {BLD}Läge:{NRM}")
    print(f"    {GRN}1.{NRM} Rekommendera nästa bok")
    print(f"    {GRN}2.{NRM} Visa gemensamt lästa böcker")
    print(f"    {GRN}3.{NRM} Kör automatisk testsvit")
    mode = input("\n  Välj läge [1]: ").strip() or "1"

    print(f"\n{'=' * 60}")
    print(f"  Smakrådgivaren startar för: {', '.join(members)}")
    print(f"{'=' * 60}")

    print("\n  Hämtar data från Notion...")
    from collections import defaultdict as _dd
    ratings = fetch_ratings(notion_token, members)
    books   = fetch_books(notion_token)

    if not books:
        print("  ❌ Inga böcker hittades i Bokregistret")
        return

    for m in members:
        if not ratings[m]:
            print(f"  ⚠️  Inga betyg hittades för {m}")

    if mode == "2":
        both_like, differ = find_shared_books(ratings, members, books, bokid_title_map())
        print(f"\n  Båda gillar ({len(both_like)} böcker):")
        for bok_id, titel, betygs in both_like[:10]:
            print(f"    {bok_id} | {titel} | {dict(zip(members, betygs))}")
        print(f"\n  Delade meningar ({len(differ)} böcker):")
        for bok_id, titel, betygs in differ[:10]:
            print(f"    {bok_id} | {titel} | {dict(zip(members, betygs))}")

    elif mode == "3":
        bok_a, bok_b, both_like, differ = auto_find_test_books(ratings, members, books)
        if not bok_a or not bok_b:
            print(f"  ⚠️  Hittade inte tillräckligt med gemensamma böcker för testsvit")
            return
        print(f"  Testbok A: {bok_a} — {books[bok_a]['titel']}")
        print(f"  Testbok B: {bok_b} — {books[bok_b]['titel']}")
        run_test_suite(notion_token, api_key, members, ratings, books, [bok_a, bok_b])

    else:
        print("\n  Genererar rekommendation...")
        result = recommend(api_key, members, ratings, books)
        print(f"\n{'=' * 60}\n  CLIO REKOMMENDERAR\n{'=' * 60}")
        print(result)

    print()
    input("  Tryck Enter för att återgå till menyn...")


def auto_find_test_books(ratings, members, books):
    """Försöker automatiskt hitta lämpliga testböcker."""
    both_like, differ = find_shared_books(ratings, members, books, bokid_title_map())
    bok_a = both_like[0][0]  if both_like else None
    bok_b = differ[0][0]     if differ    else None
    return bok_a, bok_b, both_like[:5], differ[:5]


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    load_dotenv()   # laddar .env från clio-library/ och/eller clio-tools/

    notion_token = os.environ.get("NOTION_TOKEN")
    api_key      = os.environ.get("ANTHROPIC_API_KEY")

    # Interaktivt läge om inga argument ges (t.ex. vid start från clio.py-menyn)
    if len(sys.argv) == 1:
        if not notion_token:
            sys.exit("❌ NOTION_TOKEN saknas — lägg till i clio-tools/.env")
        interactive_mode(notion_token, api_key)
        return

    parser = argparse.ArgumentParser(description="Clio Smakrådgivare — bokklubbsrekommendation")
    parser.add_argument("--members",   nargs="+", default=None,
                        help="Namn på deltagare, t.ex. Alice Ulrika")
    parser.add_argument("--list-users", action="store_true",
                        help="Lista alla användare i Betygstabellen")
    parser.add_argument("--blacklist", nargs="*", default=[],
                        help="BOK-IDs att utesluta, t.ex. BOK-0042")
    parser.add_argument("--test",      nargs=2,   default=None,
                        metavar=("BOK_BADA_GILLAR", "BOK_DELADE_MENINGAR"),
                        help="Kör testsvit med dessa två böcker")
    parser.add_argument("--auto-test", action="store_true",
                        help="Hitta testböcker automatiskt och kör testsvit")
    parser.add_argument("--find-shared", action="store_true",
                        help="Lista bara gemensamt lästa böcker och avsluta")
    args = parser.parse_args()

    if not notion_token:
        sys.exit("❌ NOTION_TOKEN saknas — lägg till i clio-tools/.env")

    # --list-users: visa användare och avsluta
    if args.list_users:
        print("\n  Registrerade läsare i Betygstabellen:")
        for name, count in fetch_users(notion_token):
            print(f"    {name}: {count} betyg")
        return

    if not args.members:
        sys.exit("❌ Ange --members eller kör utan argument för interaktivt läge")

    if not api_key and not args.find_shared:
        sys.exit("❌ ANTHROPIC_API_KEY saknas — lägg till i clio-tools/.env")

    members = args.members
    print(f"\n🔍 Smakrådgivaren startar för: {', '.join(members)}")
    print("=" * 60)

    print("\n[1/3] Hämtar data från Notion...")
    ratings = fetch_ratings(notion_token, members)
    books   = fetch_books(notion_token)

    if not books:
        sys.exit("❌ Inga böcker hittades i Bokregistret")

    # Kontrollera att vi har betyg
    for m in members:
        if not ratings[m]:
            print(f"  ⚠️  Inga betyg hittades för {m} — kontrollera att data är importerad")

    if args.find_shared:
        print("\n[2/3] Letar gemensamt lästa böcker...")
        both_like, differ = find_shared_books(ratings, members, books, bokid_title_map())
        print(f"\n  Båda gillar ({len(both_like)} böcker):")
        for bok_id, titel, betygs in both_like[:10]:
            print(f"    {bok_id} | {titel} | betyg: {dict(zip(members, betygs))}")
        print(f"\n  Delade meningar ({len(differ)} böcker):")
        for bok_id, titel, betygs in differ[:10]:
            print(f"    {bok_id} | {titel} | betyg: {dict(zip(members, betygs))}")
        return

    if args.auto_test:
        print("\n[2/3] Hittar testböcker automatiskt...")
        bok_a, bok_b, both_like, differ = auto_find_test_books(ratings, members, books)
        if not bok_a or not bok_b:
            print(f"  ⚠️  Hittade inte tillräckligt med gemensamma böcker")
            print(f"     Båda gillar: {len(both_like)}, Delade meningar: {len(differ)}")
            print(f"  Tips: Kör med --find-shared för att se vad som finns")
            sys.exit(1)
        print(f"  Testbok A (båda gillar):       {bok_a} — {books[bok_a]['titel']}")
        print(f"  Testbok B (delade meningar):   {bok_b} — {books[bok_b]['titel']}")
        print("\n[3/3] Kör testsvit...")
        run_test_suite(notion_token, api_key, members, ratings, books, [bok_a, bok_b])
        return

    if args.test:
        print("\n[2/3] Kör testsvit med angivna böcker...")
        run_test_suite(notion_token, api_key, members, ratings, books, args.test)
        return

    # Normalt läge — en rekommendation
    print("\n[2/3] Bygger smakprofiler...")
    print("\n[3/3] Genererar rekommendation...")
    result = recommend(api_key, members, ratings, books, args.blacklist)

    print("\n" + "=" * 70)
    print("  CLIO REKOMMENDERAR")
    print("=" * 70)
    print(result)
    print()


if __name__ == "__main__":
    main()
