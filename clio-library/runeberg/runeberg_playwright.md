# clio-fetch med Playwright — Runeberg-projektet

## Bakgrund

Sedan 2026-04-03 stöder `clio-fetch` två scraping-motorer:

| Motor | Flagga | Passar när |
|-------|--------|-----------|
| requests (standard) | *(ingen)* | Statiska sidor — katalog.html, verksidor |
| Playwright (Chromium) | `--engine playwright` | JS-renderade sidor |

**Runeberg.org är statisk** — `requests` räcker för fas 1 och fas 2.
Playwright behövs bara om sidan börjar använda JavaScript-rendering i framtiden.

---

## Hur du kör clio-fetch mot Runeberg

### Enstaka verksida (requests, standard)
```powershell
cd C:\Users\fredr\git\clio-tools\clio-fetch
python clio_fetch.py --url https://runeberg.org/authors/
```

### Enstaka verksida (Playwright, om sidan JS-renderats)
```powershell
python clio_fetch.py --url https://runeberg.org/strindberg/ --engine playwright
```

### Katalog rekursivt (requests)
```powershell
python clio_fetch.py --url https://runeberg.org/katalog.html --recursive
```

### Katalog rekursivt (Playwright)
```powershell
python clio_fetch.py --url https://runeberg.org/katalog.html --recursive --engine playwright
```

Output hamnar i `clio-fetch/output/` som JSON-filer.

---

## Playwright — installation (en gång)

```powershell
pip install playwright
python -m playwright install chromium
```

> OBS: Använd `python -m playwright` (inte bara `playwright`) — skript-mappen
> är inte på PATH i Windows.

---

## Prompt att ge Clio för att uppdatera skripten efter nya böcker

Klistra in detta i en ny chatt om några månader:

---

> **Läs Context Card:** https://www.notion.so/33667666d98a810aac48fed2421145d0
>
> Jag vill uppdatera runeberg-projektet i `C:\Users\fredr\git\clio-tools\clio-library\runeberg\` med nya böcker från Projekt Runeberg.
>
> Gör så här:
> 1. Läs `runeberg_README.md` och `runeberg_playwright.md` för kontext
> 2. Kör fas 1 på nytt för att hämta en uppdaterad katalog:
>    `python runeberg_fas1_katalog.py`
> 3. Jämför nya `runeberg_catalog.csv` med befintlig — vilka titlar är nya sedan sist?
> 4. Kör fas 2 (`runeberg_fas2_verk.py`) för de nya titlarna
> 5. Exportera ny CSV för Notion-import
>
> Om runeberg.org nu verkar JS-renderat (tomt innehåll), byt till
> `--engine playwright` i clio-fetch (se `runeberg_playwright.md`).

---

## Kontrollera om sidan blivit JS-renderad

Kör samma URL med båda motorerna och jämför `word_count` i JSON:

```powershell
cd C:\Users\fredr\git\clio-tools\clio-fetch
python clio_fetch.py --url https://runeberg.org/katalog.html
python clio_fetch.py --url https://runeberg.org/katalog.html --engine playwright
```

Om `requests` ger 0–50 ord men `playwright` ger hundratals → sidan har bytt till JS-rendering.
