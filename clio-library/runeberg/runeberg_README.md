# Runeberg-projektet — Arvas Familjebibliotek

## Syfte
Bygga ett sökbart index över Projekt Runebergs ~6 800 titlar,
med sammanfattningar och (senare) kontextmedvetna nyckelord.
Målet är att kunna följa ett begrepp eller ämne i texter från
olika epoker — diakron läsning med AI-assistans.

## Filer
| Fil | Beskrivning |
|-----|-------------|
| `runeberg_fas1_katalog.py` | Hämtar katalogen, sparar `runeberg_catalog.csv` |
| `runeberg_fas2_verk.py`    | Besöker varje verks sida, extraherar sammanfattning |
| `runeberg_schema.ps1`      | Skapar schemalagt Windows-jobb (kör fas 2 dagligen) |
| `runeberg_catalog.csv`     | Output fas 1 — skapas när fas 1 körs |
| `runeberg_works.csv`       | Output fas 2 — växer successivt |
| `runeberg_checkpoint.json` | Håller koll på vad som är klart |

## Snabbstart

### 1. Installera beroenden
```powershell
pip install requests beautifulsoup4
```

### 2. Kör fas 1 (en gång, ~5 min)
```powershell
cd C:\Users\<dig>\Documents\Runeberg
python runeberg_fas1_katalog.py
```
Skapar `runeberg_catalog.csv` med alla böcker på svenska/norska/danska/finska.

### 3. Testa fas 2 manuellt (10 verk)
```powershell
python runeberg_fas2_verk.py
```
Kör 150 verk per körning (ca 2,5 timmar med 1 min/anrop).

### 4. Schemalägg fas 2
```powershell
# Kör som administratör
.\runeberg_schema.ps1
```
Jobbet kör varje natt kl 02:00. Med 150 verk/dag tar hela katalogen
ca 45 dagar. Checkpoint gör att avbrott inte förlorar data.

## Notion-import
`runeberg_works.csv` är förberedd för import till Notion.
Kolumner: typ | titel | författare | år | språk | slug | url |
sammanfattning | hämtad_datum | status

## Nästa steg (Fas 3)
Lägg till kontextmedvetna nyckelord via Claude API:
- Skicka titel + författare + år + sammanfattning
- Få tillbaka 5-8 nyckelord (ämne, geografi, epok, ton)
- Möjliggör sökning som: "kolonialism 1880-tal" eller "kvinnofrågan"

## Filter
Standardinställning hämtar: Book | se, no, dk, fi, is, fo
Ändra i fas1-skriptet:
- `TYPE_FILTER = None` — alla typer inkl. Music, Periodical
- `LANG_FILTER = None` — alla språk inkl. engelska (us/de)
