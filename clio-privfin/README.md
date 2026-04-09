# clio-privfin

Privatekonomin — importera kontoutdrag, kategorisera och analysera familjens utgifter.

Del av [clio-tools](../README.md). Startas via huvudmenyn: `python clio.py` → **11**.

---

## Snabbstart

```powershell
cd clio-tools
python clio.py          # välj 11 — clio-privfin
```

Eller direkt:

```powershell
cd clio-tools/clio-privfin
python import.py "F:\Dropbox\...\kontoutdrag\Danskebank\FredriksPriv-...-20260409.xml" \
    --konto "Fredriks privatkonto" --agare "Fredrik"
python rapport.py sammanstallning
```

---

## Import via menyn

1. Välj mapp — ihågkommen mellan körningar
2. Filer visas i två grupper: **ej importerade** och **redan importerade**
3. Välj med nummer, intervall (`1-3`), kombinerat (`1,3-5`) eller `a` för alla nya
4. Kontonamn föreslås automatiskt om kontot är känt i databasen

---

## Rapporter

| Kommando | Beskrivning |
|---|---|
| `python rapport.py media` | Mediaprenumerationer per tjänst |
| `python rapport.py el` | Elkostnader (Vattenfall + Godel) |
| `python rapport.py okategoriserade` | Transaktioner utan kategori |
| `python rapport.py sammanstallning` | Översikt per kategori |
| `python rapport.py transfers` | Interna transfereringar |
| `python rapport.py manad 2026-03` | Alla transaktioner en månad |

---

## Kategorisering

Regler i `regler.json` — substring-match mot transaktionstext, case-insensitive. Redigera utan Python-kunskap.

```json
{"monster": "Netflix", "cat_id": "media", "kommentar": "Netflix streaming"}
```

---

## Filer

| Fil | Syfte |
|---|---|
| `import.py` | Parsare för Danske Bank XML/CSV → SQLite |
| `rapport.py` | Rapportgenerator |
| `regler.json` | Kategoriseringsregler |
| `schema.sql` | Databasschema |
| `familjekonomi.db` | SQLite-databas (skapas vid import) |

---

## Konton (Danske Bank)

Kontoutdrag ligger i `F:\Dropbox\ftg\arvas_koncernen\60_bokföring\kontoutdrag\Danskebank\`.

Format: `[Kontonamn]-[kontonummer]-[YYYYMMDD].xml`

---

## Kommande (sprint 2)

- PDF-format för kontoutdrag
