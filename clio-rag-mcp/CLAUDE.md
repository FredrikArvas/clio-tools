# clio-rag-mcp — CLAUDE.md

## Syfte
MCP-server som exponerar clio-rag:s Qdrant-samlingar via Streamable HTTP. Autentisering via Bearer-token med per-token samlingsbegränsning.

## Status
Aktiv

## Snabbstart
```powershell
pip install -r requirements.txt
python server.py                       # Startar MCP-server (port 4010)
```

Körs som systemd-service: `clio-rag-mcp.service` på EliteDeskGPU.

## Nyckelkod
- `server.py` — MCP HTTP-server, auth, samlingsbegränsning

## Beroenden
Externa: qdrant-client, flask
Interna: clio-core, clio-rag

## Relaterade moduler
clio-core, clio-rag

## Gotchas
Port 4010 via Tailscale. Tokens i .env: `MCP_TOKENS=token1:namn1,token2:namn2`. Per-token samlingsbegränsning: `MCP_COLLECTIONS=token1:vigil_ufo,token2:*` (* = alla publika).
