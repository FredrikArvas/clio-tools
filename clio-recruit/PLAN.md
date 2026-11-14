# Backfill analyscache — clio-agent-job
Datum: 2026-08-03

## Mål
Fylla `clio.recruiter.article_analysis` (UNIQUE article_id + profile_id) för
1 117 artiklar × 3 profiler = 3 351 kombinationer.
Analysen körs i aktiv Claude-session (subscription) — ingen API-kostnad.

## Profiler
| id | Namn | Typ |
|----|------|-----|
| 2  | CapFM SAP-rekrytering | recruiter |
| 3  | CAP — Integration Sol. Arch. | recruiter |
| 4  | CAP Dynamics | recruiter |

## Flöde (tvåstegs)
1. **Snabbscan** — titlar läses i batcher om ~200, klassas p2/p3/p4 (0–100)
2. **Djupanalys** — artiklar med score ≥ 40 hämtas med body_snippet och analyseras
3. **Import** — `import_results.py` skriver JSON → Odoo (`write_analysis_cache`)
4. **Auto-noll** — alla övriga kombinationer sparas med match_score=0

## Katalogstruktur
```
clio-recruit/
  PLAN.md                      — detta dokument
  analysis/
    scan_batch_01.json         — snabbscan resultat (0–199)
    scan_batch_02.json         — snabbscan resultat (200–399)
    ...
    deep_candidates.json       — artiklar med score ≥ 40 (alla profiler)
    deep_results.json          — fullständiga analysresultat från Claude
  results/
    final_results.json         — alla kombinationer redo för import
  import_results.py            — skriver final_results.json → Odoo
```

## Scan-format (scan_batch_NN.json)
```json
[
  {"article_id": "...", "p2": 0, "p3": 45, "p4": 0, "note": ""},
  ...
]
```

## Deep-format (deep_results.json)
```json
[
  {
    "article_id": "...",
    "profile_id": 3,
    "signal_type": "outsourcing",
    "signal_strength": "medel",
    "match_score": 65,
    "match_reason": "...",
    "potential_roles": ["Integration Architect"],
    "recommended_action": "bevaka_3man",
    "contact_hint": "..."
  },
  ...
]
```

## Status
- [x] Källkod läst (analyzer.py, odoo_reader.py, odoo_writer.py, source_base.py)
- [x] Artikeldump klar (1 117 artiklar i /tmp/articles_dump.json)
- [x] Snabbscan batch 1 (0–199)    → analysis/scan_batch_01.json  (8 kandidater ≥30)
- [x] Snabbscan batch 2 (200–399)  → analysis/scan_batch_02.json  (3 kandidater ≥30)
- [x] Snabbscan batch 3 (400–599)  → analysis/scan_batch_03.json  (1 kandidat ≥30)
- [x] Snabbscan batch 4 (600–799)  → analysis/scan_batch_04.json  (3 kandidater ≥30)
- [x] Snabbscan batch 5 (800–999)  → analysis/scan_batch_05.json  (7 kandidater ≥30)
- [x] Snabbscan batch 6 (1000–1116)→ analysis/scan_batch_06.json  (0 kandidater ≥30)
- [x] Sammanställ kandidater        → analysis/deep_candidates.json (20 artiklar, 28 kombo)
- [x] Djupanalys kandidater         → analysis/deep_results.json  (13 poster, 9 artiklar × 1-2 profiler)
- [x] Bygg final_results.json       → results/final_results.json  (3 351 poster: 18 djupanalys, 3 333 nollposter)
- [x] Import till Odoo              → 3 351 skapade, 0 fel, 0 skip (2026-08-03)
