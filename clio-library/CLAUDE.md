# CLAUDE.md — clio-library
> Läs Context Card i Notion innan du gör något annat.
> https://www.notion.so/33667666d98a810aac48fed2421145d0

---

## Miljö
- Windows / PowerShell (inte bash/Unix)
- Miljövariabler: `$env:VARIABEL = "värde"`
- Python 3
- Arbetskatalog: `C:\Users\fredr\git\clio-tools\clio-library\`

## Databaser i Notion
| Namn | Databas-ID | Data source-ID |
|------|-----------|----------------|
| Bokregister | `94906f71-ee0f-4ff8-8c4b-28e822f6e670` | `a36a4f25-56ae-4001-a476-e5437acaa88e` |
| Betyg | `41009da8-a1e7-48e2-9ed9-7f3c9406ef93` | `a06532cd-88e5-4ab1-8362-6f50d193d02d` |

> ⚠️ Äldre databas `1190a2c4-...` är borttagen — använd den aldrig.

## Scripts i detta projekt
| Script | Syfte | Körs med |
|--------|-------|----------|
| `import_books.py` | Importerar fysiska böcker till Bokregistret | `python import_books.py` |
| `enrich_books.py` | Berikar med ISBN/år/förlag via Google Books | `python enrich_books.py` |
| `match_bokid.py` | Fuzzy-matchar BOK-ID i Betygstabellen | `python match_bokid.py --dry-run` |
| `taste_recommender.py` | Smakrådgivare — bokklubbsrekommendation | se nedan |

### taste_recommender.py — snabbstart
```powershell
$env:NOTION_TOKEN = "secret_xxx"
$env:ANTHROPIC_API_KEY = "sk-ant-xxx"

# Se gemensamt lästa böcker (kräver ej API-nyckel)
python taste_recommender.py --members Alice Ulrika --find-shared

# Kör testsvit med två kända böcker
python taste_recommender.py --members Alice Ulrika --test BOK-XXXX BOK-YYYY

# Låt scriptet hitta testböcker automatiskt
python taste_recommender.py --members Alice Ulrika --auto-test
```

## Arbetsfördelning — VIKTIGT
- Fredrik importerar data till Notion. Clio läser, analyserar och rättar.
- Clio skriver **aldrig** poster direkt till Bokregistret eller Betygstabellen utan godkännande.
- Clio rättar enstaka felposter vid behov (update på specifik page_id).

## Designprinciper
- BOK-ID format: `BOK-0001` (auto_increment_id med prefix BOK)
- Betyg kopplar mot Böcker, inte Exemplar
- Klassificeringsfält (Konceptuella begrepp, Världsbild, Primärt tema, Funktion, Thema) ägs av Clio
- Känslotaggar och Anteckning ägs av familjemedlemmar

## Arkitekturdokument
- Databasschema: https://www.notion.so/33667666d98a811897b9d74565ce276c
- Notion API Gotchas: https://www.notion.so/33667666d98a811c91afd4f40925e20f
- Epic Smakrådgivaren: https://www.notion.so/33667666d98a81d8acb3ce8ac0f2ca15
