-- familjekonomi.db schema v1.0

CREATE TABLE IF NOT EXISTS accounts (
    account_id   TEXT PRIMARY KEY,  -- t.ex. "12010376889"
    namn         TEXT NOT NULL,     -- t.ex. "Bilkontot"
    bank         TEXT NOT NULL,     -- t.ex. "Danske Bank"
    typ          TEXT NOT NULL,     -- checking | savings | credit | loan
    agare        TEXT NOT NULL,     -- Fredrik | Ulrika | Gemensamt
    valuta       TEXT DEFAULT 'SEK',
    aktiv        INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transactions (
    tx_id        TEXT PRIMARY KEY,  -- hash av konto+datum+belopp+text
    account_id   TEXT NOT NULL REFERENCES accounts(account_id),
    datum        TEXT NOT NULL,     -- ISO 8601: YYYY-MM-DD
    text         TEXT NOT NULL,     -- originaltext från banken
    belopp       REAL NOT NULL,     -- negativt = uttag, positivt = insättning
    saldo        REAL,              -- saldo efter transaktion
    status       TEXT,              -- Utförd | Väntande
    avstamd      TEXT,              -- Ja | Nej
    importfil    TEXT NOT NULL,     -- källfilens namn
    importdatum  TEXT NOT NULL      -- när den importerades
);

CREATE TABLE IF NOT EXISTS categories (
    cat_id       TEXT PRIMARY KEY,
    namn         TEXT NOT NULL,
    typ          TEXT NOT NULL,     -- expense | income | transfer | ignore
    beskrivning  TEXT,
    farg         TEXT               -- hex-kod för UI
);

CREATE TABLE IF NOT EXISTS tx_categorized (
    tx_id        TEXT NOT NULL REFERENCES transactions(tx_id),
    cat_id       TEXT NOT NULL REFERENCES categories(cat_id),
    confidence   REAL DEFAULT 1.0, -- 0.0-1.0, 1.0 = manuell
    kalla        TEXT DEFAULT 'rule', -- rule | manual | ai
    kommentar    TEXT,
    PRIMARY KEY (tx_id)
);

CREATE TABLE IF NOT EXISTS transfer_pairs (
    pair_id      TEXT PRIMARY KEY,
    tx_id_ut     TEXT NOT NULL REFERENCES transactions(tx_id),
    tx_id_in     TEXT NOT NULL REFERENCES transactions(tx_id),
    belopp       REAL NOT NULL,
    bekraftad    INTEGER DEFAULT 0, -- 0 = föreslagen, 1 = bekräftad
    kommentar    TEXT
);

-- Views för enkel rapportering

CREATE VIEW IF NOT EXISTS v_resultat AS
SELECT
    t.datum,
    t.text,
    t.belopp,
    a.namn AS konto,
    a.agare,
    c.namn AS kategori,
    c.typ
FROM transactions t
JOIN accounts a ON t.account_id = a.account_id
LEFT JOIN tx_categorized tc ON t.tx_id = tc.tx_id
LEFT JOIN categories c ON tc.cat_id = c.cat_id
WHERE c.typ IN ('expense', 'income')
   OR (tc.tx_id IS NULL);  -- okategoriserade syns också

CREATE VIEW IF NOT EXISTS v_transfereringar AS
SELECT
    tp.pair_id,
    t_ut.datum,
    t_ut.text AS fran_text,
    a_ut.namn AS fran_konto,
    t_in.text AS till_text,
    a_in.namn AS till_konto,
    tp.belopp,
    tp.bekraftad
FROM transfer_pairs tp
JOIN transactions t_ut ON tp.tx_id_ut = t_ut.tx_id
JOIN transactions t_in ON tp.tx_id_in = t_in.tx_id
JOIN accounts a_ut ON t_ut.account_id = a_ut.account_id
JOIN accounts a_in ON t_in.account_id = a_in.account_id;

CREATE INDEX IF NOT EXISTS idx_tx_datum ON transactions(datum);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_text ON transactions(text);
