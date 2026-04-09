-- clio-partnerdb schema.sql
-- Schema version 1 (PRAGMA user_version = 1)
--
-- Two table classes (see ADD-002):
--
--   CORE   — shared across all Clio consumers. Never add module-specific
--            columns here. Consumers link via partner.id only.
--
--   CONTEXT — module-specific tables that currently live here for
--             referential integrity and convenience. May be extracted
--             to separate DB files if edge cases require it. Consumers
--             must never JOIN core ↔ context by anything other than
--             partner_id / references to partner(id).
--
-- Two temporal dimensions (see ADD-002):
--   valid time       → claim.valid_from / claim.valid_to
--                      event.date_from  / event.date_to
--   transaction time → audit_log.changed_at

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── CORE ──────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS partner (
    id          TEXT PRIMARY KEY,           -- uuid4, stable forever
    created_at  TEXT NOT NULL,              -- ISO 8601 UTC
    editors     TEXT NOT NULL DEFAULT '[]', -- JSON array of emails (WordPress editor model)
    is_person   INTEGER NOT NULL DEFAULT 1, -- 1 = individual, 0 or co-set with is_org
    is_org      INTEGER NOT NULL DEFAULT 0  -- 1 = organisation / company
    -- A sole trader (enskild firma) may have both is_person=1 and is_org=1
);

-- Life events: birth, death, marriage, founding, dissolution, move, baptism, …
CREATE TABLE IF NOT EXISTS event (
    id             TEXT PRIMARY KEY,
    partner_id     TEXT NOT NULL REFERENCES partner(id) ON DELETE CASCADE,
    type           TEXT NOT NULL,   -- 'birth'|'death'|'marriage'|'founding'|'dissolution'|'move'
    date_from      TEXT,            -- ISO partial: '1945', '1945-03', '1945-03-21'
    date_to        TEXT,            -- for intervals (e.g. migration period)
    date_precision TEXT,            -- 'year'|'month'|'day'|'approximate'
    place          TEXT,            -- free text city / parish / country
    place_lat      REAL,
    place_lon      REAL,
    source_id      TEXT REFERENCES source(id)
);

-- Mutable facts: name, nickname, national_id, city, occupation, note, …
CREATE TABLE IF NOT EXISTS claim (
    id          TEXT PRIMARY KEY,
    partner_id  TEXT NOT NULL REFERENCES partner(id) ON DELETE CASCADE,
    predicate   TEXT NOT NULL,  -- 'name'|'nickname'|'national_id'|'city'|'occupation'|'note'
    value       TEXT NOT NULL,  -- JSON (string for simple values, object for structured)
    valid_from  TEXT,           -- ISO partial, when this fact became true in reality
    valid_to    TEXT,           -- ISO partial, when this fact stopped being true
    is_primary  INTEGER NOT NULL DEFAULT 0,  -- 1 = use this claim for display / export
    source_id   TEXT REFERENCES source(id),
    asserted_by TEXT,           -- email or system identifier
    asserted_at TEXT NOT NULL   -- ISO 8601 UTC
);

-- Relationships between partners: spouse, parent, child, sibling, employer, …
CREATE TABLE IF NOT EXISTS relationship (
    id         TEXT PRIMARY KEY,
    from_id    TEXT NOT NULL REFERENCES partner(id) ON DELETE CASCADE,
    to_id      TEXT NOT NULL REFERENCES partner(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,  -- 'spouse'|'parent'|'child'|'sibling'|'grandparent'
                               -- |'employer'|'employee'|'member_of'|'supplier_of'
    valid_from TEXT,
    valid_to   TEXT,
    source_id  TEXT REFERENCES source(id)
);

-- Provenance: where did the data come from?
CREATE TABLE IF NOT EXISTS source (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,  -- 'gedcom'|'manual'|'csv_import'|'obit_familjesidan'|'geni'
    reference   TEXT,           -- filename, URL, gedcom xref, …
    imported_at TEXT NOT NULL,
    imported_by TEXT            -- email or 'system'
);

-- Idempotent re-import: maps external system IDs to partner.id
-- Prevents duplicate partners on repeated imports from the same source.
CREATE TABLE IF NOT EXISTS external_ref (
    system      TEXT NOT NULL,  -- e.g. 'gedcom:ChristersFredrik.ged' | 'geni' | 'folk'
    external_id TEXT NOT NULL,  -- e.g. GEDCOM @I0001@ pointer
    partner_id  TEXT NOT NULL REFERENCES partner(id) ON DELETE CASCADE,
    PRIMARY KEY (system, external_id)
);

-- ── CONTEXT ───────────────────────────────────────────────────────────────────
-- Currently owned by clio-agent-obit. See ADD-002 for extraction policy.

-- Watch list: which owner monitors which partner?
CREATE TABLE IF NOT EXISTS watch (
    owner_email TEXT NOT NULL,
    partner_id  TEXT NOT NULL REFERENCES partner(id) ON DELETE CASCADE,
    priority    TEXT NOT NULL DEFAULT 'normal',  -- 'important'|'normal'|'nice_to_know'
    source      TEXT,            -- 'gedcom'|'manual'|'csv_import'|'invitation'
    added_at    TEXT NOT NULL,   -- ISO 8601 UTC — used for first-run suppression (180 days)
    PRIMARY KEY (owner_email, partner_id)
);

-- ── AUDIT LOG ─────────────────────────────────────────────────────────────────
-- Records every mutation across all tables (transaction time).
-- Use claim.valid_from/to and event.date_from/to for valid time.
--
-- Query example — full history for a partner:
--   SELECT * FROM audit_log
--   WHERE row_key LIKE '%<uuid>%'
--   ORDER BY changed_at;

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name  TEXT NOT NULL,
    row_key     TEXT NOT NULL,   -- JSON: {"id": "uuid"} or {"owner_email": "x", "partner_id": "y"}
    operation   TEXT NOT NULL,   -- 'insert'|'update'|'delete'
    before_json TEXT,            -- NULL on insert
    after_json  TEXT,            -- NULL on delete
    changed_at  TEXT NOT NULL,   -- ISO 8601 UTC
    changed_by  TEXT NOT NULL,   -- email or 'system:import_gedcom' / 'system:cli'
    reason      TEXT             -- free text: "gedcom import from file.ged", "manual merge"
);

-- ── INDEXES ───────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_event_partner       ON event(partner_id);
CREATE INDEX IF NOT EXISTS idx_claim_partner       ON claim(partner_id);
CREATE INDEX IF NOT EXISTS idx_claim_predicate     ON claim(predicate);
CREATE INDEX IF NOT EXISTS idx_relationship_from   ON relationship(from_id);
CREATE INDEX IF NOT EXISTS idx_relationship_to     ON relationship(to_id);
CREATE INDEX IF NOT EXISTS idx_watch_owner         ON watch(owner_email);
CREATE INDEX IF NOT EXISTS idx_audit_table_row     ON audit_log(table_name, row_key);
CREATE INDEX IF NOT EXISTS idx_audit_changed_at    ON audit_log(changed_at);
