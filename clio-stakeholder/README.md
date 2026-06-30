# clio-stakeholder

Builds a reusable Excel template for **stakeholder mapping** in a Slack-based client engagement. The file holds no client data — you fill the *Rådata* tab from an export you run yourself, and the *Analys* tab works out each stakeholder's Mendelow position automatically.

---

## What it does

`build_stakeholder_excel.py` generates a 5-tab workbook:

| Tab | Purpose |
|---|---|
| `Instructions` | Purpose, step-by-step, Mendelow/RACI legends, interpretation tips |
| `Settings` | Client, period and the high/low thresholds that drive Mendelow |
| `Rådata` | One row per stakeholder — Slack metadata only, no message content |
| `Analys` | Influence/Interest (1–5) → Mendelow quadrant (auto), RACI, comms plan |
| `File History` | Version log |

The Mendelow quadrant (*Hantera nära / Håll nöjd / Håll informerad / Bevaka*) is computed from each stakeholder's Influence and Interest scores against the thresholds in `Settings`, and colour-coded. A 2×2 power/interest matrix at the bottom of `Analys` counts stakeholders per quadrant.

---

## The idea

You do the data work and keep the raw data with you (privacy + consulting ethics). The template never needs to see the client's Slack — it only structures the stripped-down metadata. A workspace admin can run an **Analytics export** (Slack admin → Analytics) that gives per-channel member activity as CSV *without message content* — exactly the right level for a stakeholder map.

---

## Running

```bash
# Build an empty template (40 stakeholder rows)
python clio-stakeholder/build_stakeholder_excel.py

# Choose output path and client name
python clio-stakeholder/build_stakeholder_excel.py --out ~/Intressentanalys.xlsx --kund "Kund AB"

# Pre-fill Rådata from a CSV export (auto-sizes the row count)
python clio-stakeholder/build_stakeholder_excel.py --csv slack_stakeholders_exempel.csv
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--out` | str | `Clio_Intressentanalys_Mall_v1.0.xlsx` | Output path |
| `--csv` | str | — | CSV to pre-fill the Rådata tab |
| `--rows` | int | 40 | Stakeholder rows to prepare |
| `--kund` | str | `[Kundnamn]` | Client/project name written to Settings |

`slack_stakeholders_exempel.csv` shows the expected column order. The first row is treated as a header and skipped on import.

---

## Workflow

1. **Export from Slack** — admin runs an Analytics export (CSV, no message content); add channel owners, admins and User Groups.
2. **Fill Rådata** — paste/type one row per stakeholder, or start with `--csv`. Anonymise anything sensitive before it leaves the client.
3. **Score Influence & Interest** — give each stakeholder 1–5 on both axes in `Analys`. Derive from the metadata (see interpretation tips in the Instructions tab).
4. **Read the map** — the Mendelow quadrant fills in automatically; add RACI and comms needs. The matrix counts stakeholders per quadrant.

---

## Interpretation tips

- **Active ≠ powerful** — high message volume usually means an operational hub, not decision authority.
- **Look for the asymmetry** — someone often *@-mentioned* but rarely *posting* usually sits on decisions.
- **Quiet admins** — accounts that own channels without appearing in the feed are easy to miss but formally central.
- **External stakeholders** — guest accounts and Slack Connect channels reveal vendors, customers and partners.

---

## Dependencies

`openpyxl>=3.1.0` (already in the repo's root `requirements.txt`).
