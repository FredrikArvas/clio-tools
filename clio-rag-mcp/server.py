"""
clio-rag-mcp/server.py
======================
MCP-server som exponerar clio-rag:s Qdrant-samlingar via Streamable HTTP.

Åtkomst: Tailscale (100.107.127.104:4010)
Auth:    Bearer-token i Authorization-header
         Tokens definieras i .env: MCP_TOKENS=token1:namn1,token2:namn2

Starta:
    python3 server.py

Systemd-service: clio-rag-mcp.service
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Lägg till clio-rag i sökvägen så att config.py och query.py kan importeras
_RAG_DIR = Path(__file__).parent.parent / "clio-rag"
sys.path.insert(0, str(_RAG_DIR))

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

import config as rag_config
from query import embed_query, search_qdrant, format_context

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

PORT      = int(os.getenv("MCP_PORT", "4010"))
HOST      = os.getenv("MCP_HOST", "0.0.0.0")

# Publik delmängd av samlingar (ej interna SSF-dokument)
PUBLIC_COLLECTIONS: dict[str, str] = {
    "vigil_ufo":      "UFO/UAP — svenska och engelska poddar och artiklar från clio-vigil",
    "vigil_uap":      "UAP — ytterligare bevakningsinnehåll (Weaponized, Pentagon m.fl.)",
    "vigil_ai":       "AI-modeller och teknik — nyheter och poddar",
    "vigil_research": "Allmän forskning och långläsningar indexerade av clio-vigil",
}

# ---------------------------------------------------------------------------
# Token-hantering
# ---------------------------------------------------------------------------

def _load_tokens() -> dict[str, str]:
    """
    Läser MCP_TOKENS=token1:namn1,token2:namn2 från env.
    Returnerar {token: namn}.
    """
    raw = os.getenv("MCP_TOKENS", "")
    tokens: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if ":" in part:
            tok, name = part.split(":", 1)
            tokens[tok.strip()] = name.strip()
        elif part:
            tokens[part] = "anonym"
    if not tokens:
        _logger.warning("Inga MCP_TOKENS konfigurerade — servern är öppen!")
    return tokens

VALID_TOKENS: dict[str, str] = _load_tokens()


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Tillåt health-check utan token
        if request.url.path in ("/health", "/"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()

        if not VALID_TOKENS:
            # Ingen konfigurerad — tillåt allt (dev-läge)
            return await call_next(request)

        if token not in VALID_TOKENS:
            _logger.warning("Obehörig förfrågan från %s", request.client)
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        _logger.info("Förfrågan från: %s", VALID_TOKENS[token])
        return await call_next(request)


# ---------------------------------------------------------------------------
# MCP-server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name        = "clio-rag",
    instructions = (
        "Sök i clio:s indexerade kunskapsbas om UFO/UAP och AI. "
        "Använd list_collections för att se vad som finns, "
        "sedan search för att ställa frågor mot en specifik samling."
    ),
)

mcp.add_middleware(BearerAuthMiddleware)


@mcp.tool(
    description=(
        "Sök i en RAG-samling och returnera relevanta textpassager med källreferenser. "
        "Returnerar de top_k mest relevanta passagerna utan att anropa en LLM — "
        "passagerna kan sedan användas som kontext för att svara på en fråga."
    )
)
def search(
    query: str,
    collection: str = "vigil_ufo",
    top_k: int = 5,
) -> dict:
    """
    Söker i Qdrant och returnerar råa passage-chunks med metadata.

    Args:
        query:      Fråga eller sökterm på valfritt språk.
        collection: Samling att söka i (se list_collections).
        top_k:      Antal passages att returnera (1–20).
    """
    top_k = max(1, min(top_k, 20))

    if collection not in PUBLIC_COLLECTIONS:
        return {
            "error": f"Samling '{collection}' är inte tillgänglig. "
                     f"Tillgängliga: {list(PUBLIC_COLLECTIONS.keys())}"
        }

    try:
        vector = embed_query(query)
        hits   = search_qdrant(vector, top_k=top_k, collection=collection)
    except Exception as exc:
        _logger.error("Sökfel: %s", exc)
        return {"error": str(exc)}

    if not hits:
        return {"passages": [], "message": f"Inga träffar i '{collection}' för: {query}"}

    passages = []
    for hit in hits:
        p = hit.payload
        passages.append({
            "score":    round(hit.score, 4),
            "title":    p.get("title", ""),
            "source":   p.get("source_name", p.get("title", "")),
            "text":     p.get("summary", p.get("text", ""))[:1500],
            "page_start": p.get("ext_page_start"),
            "page_end":   p.get("ext_page_end"),
            "url":      p.get("url", p.get("ext_notion_url", "")),
        })

    return {
        "collection": collection,
        "query":      query,
        "passages":   passages,
    }


@mcp.tool(
    description="Listar tillgängliga RAG-samlingar med beskrivningar och antal indexerade chunks."
)
def list_collections() -> dict:
    """Returnerar alla publikt tillgängliga samlingar."""
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="localhost", port=6333)
        sizes  = {c.name: client.get_collection(c.name).points_count
                  for c in client.get_collections().collections}
    except Exception:
        sizes = {}

    return {
        "collections": [
            {
                "name":        name,
                "description": desc,
                "chunks":      sizes.get(name, "?"),
            }
            for name, desc in PUBLIC_COLLECTIONS.items()
        ]
    }


# ---------------------------------------------------------------------------
# Hälsokontroll (HTTP GET /health)
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    from starlette.responses import JSONResponse as JR
    return JR({"status": "ok", "server": "clio-rag-mcp"})


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _logger.info("Startar clio-rag-mcp på %s:%d", HOST, PORT)
    _logger.info("Publiga samlingar: %s", list(PUBLIC_COLLECTIONS.keys()))
    _logger.info("Aktiva tokens: %d st", len(VALID_TOKENS))

    mcp.run(
        transport = "streamable-http",
        host      = HOST,
        port      = PORT,
    )
