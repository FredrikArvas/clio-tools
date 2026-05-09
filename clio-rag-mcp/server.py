"""
clio-rag-mcp/server.py
======================
MCP-server som exponerar clio-rag:s Qdrant-samlingar via Streamable HTTP.

Åtkomst: Tailscale (100.107.127.104:4010)
Auth:    Bearer-token i Authorization-header
         Tokens definieras i .env: MCP_TOKENS=token1:namn1,token2:namn2
         Per-token samlingsbegränsning: MCP_COLLECTIONS=token1:vigil_ufo+vigil_uap,token2:*
         (* = alla publika samlingar)

Starta:
    python3 server.py

Systemd-service: clio-rag-mcp.service
"""

from __future__ import annotations

import contextvars
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Lägg till clio-rag i sökvägen så att config.py och query.py kan importeras
_RAG_DIR = Path(__file__).parent.parent / "clio-rag"
sys.path.insert(0, str(_RAG_DIR))

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

import config as rag_config
from query import embed_query, search_qdrant

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

PORT = int(os.getenv("MCP_PORT", "4010"))
HOST = os.getenv("MCP_HOST", "0.0.0.0")

# Publik delmängd av samlingar (ej interna SSF-dokument)
PUBLIC_COLLECTIONS: dict[str, str] = {
    "vigil_ufo":      "UFO/UAP — svenska och engelska poddar och artiklar från clio-vigil",
    "vigil_uap":      "UAP — ytterligare bevakningsinnehåll (Weaponized, Pentagon m.fl.)",
    "vigil_ai":       "AI-modeller och teknik — nyheter och poddar",
    "vigil_research": "Allmän forskning och långläsningar indexerade av clio-vigil",
}

# ContextVar: samlingar tillåtna för innevarande request (None = alla publika)
_allowed: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar(
    "allowed_collections", default=None
)

# ---------------------------------------------------------------------------
# Token-hantering
# ---------------------------------------------------------------------------

def _load_tokens() -> dict[str, str]:
    """MCP_TOKENS=token1:namn1,token2:namn2 → {token: namn}"""
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


def _load_token_collections() -> dict[str, set[str]]:
    """
    MCP_COLLECTIONS=token1:vigil_ufo+vigil_uap,token2:*
    → {token: {"vigil_ufo","vigil_uap"}}
    Token som saknas i MCP_COLLECTIONS får tillgång till alla publika samlingar.
    """
    raw = os.getenv("MCP_COLLECTIONS", "")
    mapping: dict[str, set[str]] = {}
    for part in raw.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        tok, cols_str = part.split(":", 1)
        tok = tok.strip()
        if cols_str.strip() == "*":
            mapping[tok] = set(PUBLIC_COLLECTIONS.keys())
        else:
            mapping[tok] = {c.strip() for c in cols_str.split("+")}
    return mapping


VALID_TOKENS: dict[str, str]          = _load_tokens()
TOKEN_COLLECTIONS: dict[str, set[str]] = _load_token_collections()


# ---------------------------------------------------------------------------
# ASGI-middleware: autentisering + samlingsbegränsning
# ---------------------------------------------------------------------------

class BearerAuthMiddleware:
    """Kontrollerar Bearer-token och sätter tillåtna samlingar i ContextVar."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path   = scope.get("path", "")
        method = scope.get("method", "")
        if path in ("/health", "/") or method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth    = headers.get(b"authorization", b"").decode()
        token   = auth.removeprefix("Bearer ").strip()

        if VALID_TOKENS and token not in VALID_TOKENS:
            _logger.warning("Obehörig förfrågan (path=%s)", path)
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        name = VALID_TOKENS.get(token, "anonym")
        _logger.info("Förfrågan från: %s", name)

        # Sätt tillåtna samlingar för detta request
        allowed = TOKEN_COLLECTIONS.get(token)   # None → inga restriktioner
        token_var = _allowed.set(allowed)
        try:
            await self.app(scope, receive, send)
        finally:
            _allowed.reset(token_var)


# ---------------------------------------------------------------------------
# MCP-server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name         = "clio-rag",
    instructions = (
        "Sök i clio:s indexerade kunskapsbas om UFO/UAP och AI. "
        "Använd list_collections för att se vad som finns, "
        "sedan search för att ställa frågor mot en specifik samling."
    ),
)


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

    # Kontrollera mot publika samlingar
    if collection not in PUBLIC_COLLECTIONS:
        return {
            "error": f"Samling '{collection}' är inte tillgänglig. "
                     f"Tillgängliga: {list(_visible_collections().keys())}"
        }

    # Kontrollera per-token begränsning
    allowed = _allowed.get()
    if allowed is not None and collection not in allowed:
        return {
            "error": f"Ditt token har inte tillgång till '{collection}'. "
                     f"Tillgängliga: {sorted(allowed)}"
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
            "score":      round(hit.score, 4),
            "title":      p.get("title", ""),
            "source":     p.get("source_name", p.get("title", "")),
            "text":       p.get("summary", p.get("text", ""))[:1500],
            "page_start": p.get("ext_page_start"),
            "page_end":   p.get("ext_page_end"),
            "url":        p.get("url", p.get("ext_notion_url", "")),
        })

    return {"collection": collection, "query": query, "passages": passages}


@mcp.tool(
    description="Listar tillgängliga RAG-samlingar med beskrivningar och antal indexerade chunks."
)
def list_collections() -> dict:
    """Returnerar samlingar tillgängliga för detta token."""
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host="localhost", port=6333)
        sizes  = {c.name: client.get_collection(c.name).points_count
                  for c in client.get_collections().collections}
    except Exception:
        sizes = {}

    visible = _visible_collections()
    return {
        "collections": [
            {"name": name, "description": desc, "chunks": sizes.get(name, "?")}
            for name, desc in visible.items()
        ]
    }


def _visible_collections() -> dict[str, str]:
    """Filtrerar PUBLIC_COLLECTIONS efter per-token begränsning."""
    allowed = _allowed.get()
    if allowed is None:
        return PUBLIC_COLLECTIONS
    return {k: v for k, v in PUBLIC_COLLECTIONS.items() if k in allowed}


# ---------------------------------------------------------------------------
# REST /search — enkel endpoint för browser-klienter (med CORS)
# ---------------------------------------------------------------------------

@mcp.custom_route("/search", methods=["POST", "OPTIONS"])
async def rest_search(request: Request):
    """
    POST /search  { "query": "...", "collection": "vigil_ufo", "top_k": 5 }
    Authorization: Bearer <token>
    Returnerar samma format som MCP-verktyget search().
    """
    if request.method == "OPTIONS":
        return JSONResponse({}, headers={
            "Access-Control-Allow-Origin":  "*",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        })

    # Auth
    auth  = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if VALID_TOKENS and token not in VALID_TOKENS:
        return JSONResponse({"error": "Unauthorized"}, status_code=401,
                            headers={"Access-Control-Allow-Origin": "*"})

    # Sätt tillåtna samlingar
    allowed = TOKEN_COLLECTIONS.get(token)
    token_var = _allowed.set(allowed)

    try:
        body       = await request.json()
        query      = body.get("query", "").strip()
        collection = body.get("collection", "vigil_ufo")
        top_k      = int(body.get("top_k", 5))

        if not query:
            return JSONResponse({"error": "query saknas"}, status_code=400,
                                headers={"Access-Control-Allow-Origin": "*"})

        result = search(query=query, collection=collection, top_k=top_k)
        return JSONResponse(result, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500,
                            headers={"Access-Control-Allow-Origin": "*"})
    finally:
        _allowed.reset(token_var)


# ---------------------------------------------------------------------------
# REST /chat — RAG + Claude på servern (webbläsaren behöver ingen API-nyckel)
# ---------------------------------------------------------------------------

CHAT_SYSTEM = (
    "Du är en hjälpsam assistent med tillgång till clio:s indexerade kunskapsbas. "
    "Du får relevanta textpassager och ska svara på frågan baserat på dem. "
    "Ange källhänvisning i formatet [Källtitel] efter påståenden från passagerna. "
    "Om informationen saknas, säg det tydligt. "
    "Svara på svenska om frågan är på svenska, annars på frågans språk. "
    "Var koncis — 3–6 meningar om inget annat efterfrågas."
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
}


@mcp.custom_route("/chat", methods=["POST", "OPTIONS"])
async def rest_chat(request: Request):
    """
    POST /chat  { "query": "...", "collection": "vigil_ufo", "top_k": 6, "history": [...] }
    Söker i RAG, anropar Claude på servern, returnerar { answer, sources }.
    """
    if request.method == "OPTIONS":
        return JSONResponse({}, headers=CORS_HEADERS)

    auth  = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if VALID_TOKENS and token not in VALID_TOKENS:
        return JSONResponse({"error": "Unauthorized"}, status_code=401,
                            headers=CORS_HEADERS)

    allowed   = TOKEN_COLLECTIONS.get(token)
    token_var = _allowed.set(allowed)

    try:
        import anthropic as _anthropic
        body       = await request.json()
        query      = body.get("query", "").strip()
        collection = body.get("collection", "vigil_ufo")
        top_k      = int(body.get("top_k", 6))
        history    = body.get("history", [])

        if not query:
            return JSONResponse({"error": "query saknas"}, status_code=400,
                                headers=CORS_HEADERS)

        # Kontrollera samlingsbegränsning
        if allowed is not None and collection not in allowed:
            return JSONResponse(
                {"error": f"Ingen åtkomst till '{collection}'. Tillgängliga: {sorted(allowed)}"},
                status_code=403, headers=CORS_HEADERS,
            )

        # RAG-sökning
        vector = embed_query(query)
        hits   = search_qdrant(vector, top_k=top_k, collection=collection)
        if not hits:
            return JSONResponse(
                {"answer": f"Inga träffar i '{collection}' för den frågan.", "sources": []},
                headers=CORS_HEADERS,
            )

        context = "\n\n".join(
            f"[Passage {i+1} — {h.payload.get('title','')}]\n"
            f"{h.payload.get('summary', h.payload.get('text',''))[:1500]}"
            for i, h in enumerate(hits)
        )

        user_content = f"Passager från kunskapsbasen:\n\n{context}\n\n---\n\nFråga: {query}"

        msgs = [m for m in history[-8:] if m.get("role") in ("user","assistant")]
        msgs.append({"role": "user", "content": user_content})

        client = _anthropic.Anthropic()
        resp   = client.messages.create(
            model      = "claude-3-5-sonnet-20241022",
            max_tokens = 1024,
            system     = CHAT_SYSTEM,
            messages   = msgs,
        )
        answer = resp.content[0].text

        sources = [
            {"score": round(h.score, 3), "title": h.payload.get("title",""),
             "url": h.payload.get("url", h.payload.get("ext_notion_url",""))}
            for h in hits
        ]
        return JSONResponse({"answer": answer, "sources": sources}, headers=CORS_HEADERS)

    except Exception as exc:
        _logger.error("/chat fel: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500, headers=CORS_HEADERS)
    finally:
        _allowed.reset(token_var)


# ---------------------------------------------------------------------------
# Hälsokontroll
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"status": "ok", "server": "clio-rag-mcp"})


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _logger.info("Startar clio-rag-mcp på %s:%d", HOST, PORT)
    _logger.info("Publiga samlingar: %s", list(PUBLIC_COLLECTIONS.keys()))
    _logger.info("Aktiva tokens: %d st", len(VALID_TOKENS))
    _logger.info("Token-begränsningar: %d konfigurerade", len(TOKEN_COLLECTIONS))

    mcp.run(
        transport  = "streamable-http",
        host       = HOST,
        port       = PORT,
        middleware = [Middleware(BearerAuthMiddleware)],
    )
