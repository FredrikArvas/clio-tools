# clio-agent-odoo — CLAUDE.md

## Syfte
Flask-endpoint som tar emot meddelanden från Odoo #clio-kanalen, anropar Claude API och postar svaret tillbaka. Stöder RAG via projektminne och är databasagnostisk.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python main.py              # Startar Flask-server
```

## Nyckelkod
- `agent.py` — Flask-endpoint, Claude API-anrop, kanalsvar
- `odoo_reply.py` — XML-RPC-svar till Odoo

## Beroenden
Externa: flask, anthropic, xmlrpc
Interna: clio-core, clio_odoo

## Relaterade moduler
clio-core, clio_odoo, clio-rag

## Gotchas
Webhook-payload måste innehålla db + bot_login + bot_password (agenten är databasagnostisk sedan 2026-04-28). CHANNEL_RAG_MAP definierar vilka kanaler som söker projektminne. Kräver ANTHROPIC_API_KEY i .env.
