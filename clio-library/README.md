# clio-library

Enriches a Notion book database with metadata from Google Books API — publication year, ISBN, and publisher.

---

## What it does

`enrich_books.py` queries the Notion database for all pages where **År** (Year) is empty, looks up each book in Google Books by title and author, and writes back any found metadata (year, ISBN, publisher).

Progress is saved to `enrich_progress.json` every 25 books so a run can be interrupted and resumed without duplicating work.

---

## Setup

### 1. Create a Notion integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) → create a new internal integration.
2. Copy the **Internal Integration Token** (starts with `secret_...`).
3. Open your Notion book database → **···** → **Connect to** → select your integration.

### 2. Save the token

Run the setup script once — it writes your token to `.env` in this folder:

```powershell
python clio-library\setup_credentials.py
```

`enrich_books.py` loads the `.env` file automatically on every run. The file is git-ignored.

---

## Running

```powershell
# Normal run — enrich all books missing a year
python clio-library\enrich_books.py

# Dry run — shows what would be updated, writes nothing to Notion
python clio-library\enrich_books.py --dry-run

# Limit to N books (useful for testing)
python clio-library\enrich_books.py --limit 10

# Longer delay between API calls (default: 0.5 s)
python clio-library\enrich_books.py --delay 1.0

# Filter by language (sv, en, de, …)
python clio-library\enrich_books.py --lang sv

# Combine flags
python clio-library\enrich_books.py --dry-run --limit 5 --lang en
```

Or launch from the main menu: `python clio.py` → **5. clio-library**.

---

## Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--dry-run` | flag | off | Log results but write nothing to Notion |
| `--limit N` | int | 0 (all) | Stop after enriching N books |
| `--delay S` | float | 0.5 | Seconds between API calls |
| `--lang CODE` | str | — | Only process books where Notion `Språk` equals CODE |

---

## Notion database properties

| Property | Type | Role |
|---|---|---|
| `Titel` | Title | Book title used for lookup |
| `Författare` | Rich text | Author used for lookup |
| `Språk` | Select | Language filter (optional) |
| `År` | Number | Written by this script |
| `ISBN` | Rich text | Written by this script |
| `Förlag` | Rich text | Written by this script |

---

## Files

| File | Purpose |
|---|---|
| `enrich_books.py` | Main script |
| `setup_credentials.py` | One-time setup — saves token to `.env` |
| `.env` | Your Notion token (git-ignored) |
| `.env.example` | Template |
| `enrich_books.log` | Warnings and errors (auto-created) |
| `enrich_progress.json` | Checkpoint, deleted when a run completes fully |

---

## Dependencies

No extra packages — uses only Python standard library (`urllib`, `json`, `argparse`, `logging`, `pathlib`).
