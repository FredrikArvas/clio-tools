# ADD — Behörighetsvisning i Odoo för clio-agent-mail

**Version:** 1.0
**Datum:** 2026-05-23
**Status:** Beslutad — implementeras

---

## 1. Bakgrund

`clio_mail_permissions`-modulen i Odoo finns och är kodmässigt klar — listvy,
formulär, synkknapp, write-through till agenten. Men `/mail/permissions/json`
returnerar alltid `{"users": []}` eftersom `fetch_matrix` i
`clio_access/notion_source.py` förväntar sig pipe-separerade code-block-rader,
medan behörighetsmatrisen i Notion faktiskt är lagrad som en riktig Notion-tabell
(`table`/`table_row`-block). Dessa är inkompatibla format.

Dessutom saknas Jessica Leijer (`jessica@leijer.se`) helt i matrisen — hon faller
igenom till vitlistningslistan i Notion och tilldelas implicit nivå `whitelisted`.

---

## 2. Beslut: Alt B — SQLite som källsystem

Behörigheter lagras i `state.db` på servern (ny tabell `permissions`). Odoo är
primärt redigeringsgränssnitt och skriver direkt via clio-service. Notion-sidan
bevaras som historisk referens men används inte längre av agenten.

**Varför Alt B:**
- Odoo föredras framför Notion som gränssnitt
- SQLite-läsning i hot path är ~0 ms — inget behov av TTL-cache
- Direkt effekt vid behörighetsändring (ingen 15-min cache-fördröjning)
- Frågebart via `sqlite3` från Claude Code/SSH utan extra tooling

---

## 3. Komponenter som ändras

| Komponent | Fil | Ändring |
|-----------|-----|---------|
| Tillståndshantering | `state.py` | Ny tabell `permissions`, CRUD-funktioner |
| Behörighetslogik | `clio_access/access.py` | SQLite-källa via `db_path`-parameter |
| Klassificering | `classifier.py` | Skickar `db_path` till `AccessManager.from_config()` |
| HTTP-brygga | `clio_service.py` | Routes använder `state` istf `clio_access.notion_source` |
| Odoo-modell | `clio_mail_permissions/` | Lägg till `po-pmo` i Selection |
| Migrering | `migrate_permissions_notion_to_db.py` | Engångskörning Notion → SQLite |
| Tester | `tests/test_permissions_scenarios.py` | Ny testsvit |

---

## 4. Datamodell — tabell `permissions`

```sql
CREATE TABLE IF NOT EXISTS permissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT    NOT NULL UNIQUE,
    level       TEXT    NOT NULL DEFAULT 'whitelisted',
    accounts    TEXT    NOT NULL DEFAULT '*',
    kodord_read TEXT    NOT NULL DEFAULT '',
    kodord_rw   TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

Fält:
- `level` — admin | write | coded | whitelisted | denied | po-pmo
- `accounts` — kommaseparerade account_key, `*` = alla
- `kodord_read` — kommaseparerade kodord med läsrätt
- `kodord_rw` — kommaseparerade kodord med läs+skrivrätt

---

## 5. API-flöde

```
Odoo (redigering)
  → POST /mail/permissions/update   (clio_service.py)
    → state.upsert_permission()     (state.py → state.db)

Odoo (synk-knapp)
  → GET /mail/permissions/json      (clio_service.py)
    → state.list_permissions()      (state.py → state.db)

Klassificering (inkommande mail)
  → AccessManager.get_level()       (clio_access/access.py)
    → _resolve_from_db()            (direkt SQLite, ingen cache)
```

---

## 6. Automattestfall

### 6.1 Grundläggande behörighetsnivåer (P-serien)

| ID | Beskrivning | Indata | Förväntat |
|----|-------------|--------|-----------|
| P-01 | Känd adress returnerar rätt nivå | jessica@leijer.se → coded i DB | get_permission()["level"] == "coded" |
| P-02 | Okänd adress returnerar None | okänd@test.se | get_permission() is None |
| P-03 | Upsert skapar ny rad | ny@test.se, whitelisted | Rad finns i DB |
| P-04 | Upsert uppdaterar befintlig | jessica@leijer.se, write | Nivå ändrad, updated_at uppdaterad |
| P-05 | Accounts-begränsning | ulrika@arvas.se, accounts=krut,clio | Rätt lista returneras |

### 6.2 Dialog-scenariot — vanlig konversation (D-serien)

Jessica mailer clio@ utan aktiv intervjusession.

| ID | Nivå | Förväntat action |
|----|------|-----------------|
| D-01 | whitelisted | AUTO_SEND |
| D-02 | write | SELF_QUERY |
| D-03 | denied | IGNORE |
| D-04 | Ej i DB, på vitlista | AUTO_SEND |
| D-05 | Ej i DB, ej på vitlista | SEND_FOR_APPROVAL |

Setup: mock_state.get_permission returnerar angiven nivå.
mock_notion_whitelist styr D-04/05 separat.

### 6.3 Intervju-scenariot — aktiv session (I-serien)

Aktiv interview_session finns för Jessica. Behörighetsnivån ska inte blockera.

| ID | Nivå | Aktiv session | Förväntat action |
|----|------|--------------|-----------------|
| I-01 | whitelisted | Ja | INTERVIEW |
| I-02 | denied | Ja | INTERVIEW (session trumfar) |
| I-03 | coded, kodord matchar ej | Ja | INTERVIEW (session trumfar) |
| I-04 | whitelisted | Nej | AUTO_SEND |
| I-05 | Session stoppad under tråd | Ja → Nej | AUTO_SEND vid nästa mail |

### 6.4 Synk Odoo ↔ service ↔ DB (S-serien)

| ID | Beskrivning | Förväntat |
|----|-------------|-----------|
| S-01 | GET /mail/permissions/json, 0 rader | {"ok": true, "users": []} |
| S-02 | GET /mail/permissions/json, 2 rader | Lista med rätt fält |
| S-03 | POST /mail/permissions/update ny rad | Rad skapas i DB |
| S-04 | POST /mail/permissions/update uppdatering | Befintlig rad uppdateras |
| S-05 | Saknat email-fält | {"ok": false, "error": ...} |

### 6.5 Migrering (M-serien)

| ID | Beskrivning | Förväntat |
|----|-------------|-----------|
| M-01 | Idempotent — kör två gånger | Inga dubletter |
| M-02 | Jessica saknas i Notion → läggs till som whitelisted | Finns i DB |

---

## 7. Implementationsordning

1. `state.py` — tabell + CRUD
2. `clio_service.py` — routes
3. `clio_access/access.py` — SQLite-källa
4. `classifier.py` — db_path till from_config()
5. Odoo-modell — po-pmo
6. Migreringsscript
7. Tester
8. Kör migrering, starta om clio_service, verifiera Odoo-synk

---

## 8. Backlog (ej i detta scope)

- Mailhistorik-länk från behörighetsvyn i Odoo (klicka på Jessica → se hennes mail)
- Notion-tabellen som readonly-export (valfritt framtida steg)

---

## 9. Öppna frågor (lösta)

| Fråga | Beslut |
|-------|--------|
| Notion eller SQLite som källsystem? | SQLite (Alt B) |
| Cache-TTL för SQLite? | Ingen cache — direkt läsning |
| Mailhistorik-länk? | Backlog |
| po-pmo-roll i Odoo? | Ja, läggs till |
