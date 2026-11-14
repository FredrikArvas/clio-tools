# clio-bmc — CLAUDE.md

## Syfte
Berikar BMC-coachsessioner (Business Model Canvas) med Claude-analys och sparar resultaten till Notion. Importerar handoff-JSON, analyserar block och pushar till Notion.

## Status
Aktiv

## Snabbstart
```powershell
python main.py --bolag "Acme AB" --version as-is --step all --input session.json
python main.py --bolag "Acme AB" --version as-is --step enrich --block vp
python main.py --bolag "Acme AB" --version as-is --step status
```

## Nyckelkod
- `main.py` — CLI entry point, steg-dispatcher
- `session.py` — Sessionshantering och block-navigering

## Beroenden
Externa: anthropic
Interna: clio-core

## Relaterade moduler
clio-core

## Gotchas
Block namnges som kortkommandon (vp, m, c etc.). Kräver Notion-token i .env.
