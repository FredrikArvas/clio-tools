import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from store import SessionStore

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clio-bridge-gsf")

BRIDGE_SECRET = os.environ["BRIDGE_SECRET"]
BRIDGE_BACKEND = os.environ.get("BRIDGE_BACKEND", "api")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAX_MESSAGE_CHARS = int(os.environ.get("MAX_MESSAGE_CHARS", "4000"))
MAX_TURNS = int(os.environ.get("MAX_TURNS", "60"))
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "10"))
SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", "30"))
DB_PATH = os.environ.get("DB_PATH", "./sessions.db")
MODEL_CHAT_API = os.environ.get("MODEL_CHAT_API", "claude-sonnet-4-6")
MODEL_EXTRACT_API = os.environ.get("MODEL_EXTRACT_API", "claude-haiku-4-5-20251001")

if BRIDGE_BACKEND == "api" and not ANTHROPIC_API_KEY:
    raise RuntimeError("BRIDGE_BACKEND=api kraver ANTHROPIC_API_KEY i .env")

SYSTEM_PROMPT_TEMPLATE = """\
Du ar Clio, en varm och nyfiken intervjuare som hjalper familjer i Guldboda \
att beratta sin fastighetshistoria till GSF:s 80-arsjubileumsskrift.

Kand information om fastigheten:
- Beteckning: {namn}
- Forvarvsdatum: {forvarvsdatum}

Anvand denna information aktivt — fraga inte om saker du redan vet.

Ditt uppdrag ar att stalla nedanstaende 10 fragor i naturlig, foljsam ordning — \
inte som ett stelbent formular. Lyssna aktivt, stall garna en spontan foljdfraga \
om nagot ar intressant, och hjalp familjen att formulera minnen i ord.

Fragelista (stall dem ungefarligt i denna ordning):
{fragor}

Regler:
- Svara alltid pa svenska.
- En fraga (eller kortare uppfoljning) per svar — overskolj aldrig med flera fragor.
- Hall tonen varm, nyfiken och respektfull.
- Fraga 10 handlar om samtycke — stall den mot slutet och formulera den tydligt.
- Skriv inte berattelsen at familjen — coacha dem att beratta sjalva.
- Nar alla 10 fragor ar besvarade (eller familjen signalerar att de ar klara): \
avsluta med en kort summering och en instruktion att klicka pa "Skicka in".\
"""

EXTRACT_SYSTEM_PROMPT = """\
Du far ett samtal mellan Clio och en familj, samt en numrerad frageliste. \
Mappa familjens svar i samtalet till respektive fraga. Svara ENDAST med giltig \
JSON pa formen {"1": "...", "2": "...", ...} dar nyckeln ar fragans nummer som \
strang och vardet ar familjens svar sammanfattat i deras egna ord (eller tom \
strang om frageomradet inte besvarats). Inget annat an JSON i svaret.\
"""


def _cli_env() -> dict:
    env = os.environ.copy()
    if BRIDGE_BACKEND == "api":
        env["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    else:
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def _fragor_text(fragor: list) -> str:
    return "\n".join(f"{nr}. {rubrik}: {text}" for nr, rubrik, text in fragor)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]
    return text.strip()


class RateLimiter:
    def __init__(self, per_minute: int):
        self._per_minute = per_minute
        self._hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = self._hits.setdefault(key, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self._per_minute:
            return False
        window.append(now)
        return True


store: SessionStore
rate_limiter = RateLimiter(RATE_LIMIT_PER_MIN)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store
    store = SessionStore(DB_PATH)
    await store.init()
    cleanup_task = asyncio.create_task(_cleanup_loop())
    logger.info("clio-bridge-gsf started, backend=%s", BRIDGE_BACKEND)
    yield
    cleanup_task.cancel()


async def _cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            n = await store.purge_stale(SESSION_MAX_AGE_DAYS)
            if n:
                logger.info("purged %d stale sessions", n)
        except Exception:
            logger.exception("cleanup failed")


app = FastAPI(lifespan=lifespan)


def _check_secret(x_bridge_secret: str | None):
    if x_bridge_secret != BRIDGE_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")


class ChatRequest(BaseModel):
    fastighet_token: str
    namn: str = ""
    forvarvsdatum: str = ""
    message: str
    fragor: list | None = None
    history: list | None = None


class ExtractRequest(BaseModel):
    fastighet_token: str
    history: list
    fragor: list


@app.get("/health")
async def health(x_bridge_secret: str | None = Header(default=None)):
    _check_secret(x_bridge_secret)
    return {"status": "ok", "backend": BRIDGE_BACKEND, "sessions": await store.count()}


async def _run_query(prompt: str, system_prompt: str, resume_id: str | None, model: str | None):
    opts = ClaudeAgentOptions(
        system_prompt=system_prompt,
        resume=resume_id,
        max_turns=1,
        model=model if BRIDGE_BACKEND == "api" else None,
        env=_cli_env(),
        tools=[],
        setting_sources=[],
    )
    reply = None
    session_id = resume_id
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    reply = block.text
        if isinstance(msg, ResultMessage):
            session_id = msg.session_id
    return session_id, reply


@app.post("/chat")
async def chat(req: ChatRequest, x_bridge_secret: str | None = Header(default=None)):
    _check_secret(x_bridge_secret)

    if len(req.message) > MAX_MESSAGE_CHARS:
        return {"error": "for_langt_meddelande"}
    if not rate_limiter.allow(req.fastighet_token):
        return {"error": "rate_limit"}

    lock = await store.lock_for(req.fastighet_token)
    async with lock:
        row = await store.get(req.fastighet_token)

        if row and row.turns >= MAX_TURNS:
            return {"error": "for_manga_turer"}

        resume_id = row.session_id if row else None
        turns = row.turns if row else 0

        if row is None:
            if not req.fragor:
                raise HTTPException(400, "fragor kravs for ny session")
            namn = req.namn
            fragor = req.fragor
        else:
            namn = row.namn
            fragor = json.loads(row.fragor_json)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            namn=namn,
            forvarvsdatum=req.forvarvsdatum or "okant",
            fragor=_fragor_text(fragor),
        )

        try:
            new_session_id, reply = await _run_query(
                prompt=req.message,
                system_prompt=system_prompt,
                resume_id=resume_id,
                model=MODEL_CHAT_API,
            )
        except Exception:
            if resume_id is not None and req.history:
                logger.warning(
                    "resume miss for token %s, rebuilding from history", req.fastighet_token
                )
                transcript = "\n".join(f"{m['role']}: {m['content']}" for m in req.history)
                rebuild_prompt = (
                    f"[Samtalet aterupptas efter avbrott. Tidigare dialog:]\n{transcript}\n\n"
                    f"[Nytt meddelande fran familjen:]\n{req.message}"
                )
                try:
                    new_session_id, reply = await _run_query(
                        prompt=rebuild_prompt,
                        system_prompt=system_prompt,
                        resume_id=None,
                        model=MODEL_CHAT_API,
                    )
                except Exception:
                    logger.exception("chat rebuild also failed for token %s", req.fastighet_token)
                    return {"error": "backend_fel"}
            else:
                logger.exception("chat backend error for token %s", req.fastighet_token)
                return {"error": "backend_fel"}

        if not new_session_id or reply is None:
            return {"error": "backend_fel"}

        turns += 1
        await store.upsert(
            req.fastighet_token, new_session_id, turns, namn, json.dumps(fragor, ensure_ascii=False)
        )
        return {"reply": reply, "session_id": new_session_id, "turns": turns}


@app.post("/extract")
async def extract(req: ExtractRequest, x_bridge_secret: str | None = Header(default=None)):
    _check_secret(x_bridge_secret)

    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in req.history)
    prompt = (
        f"Frageliste:\n{_fragor_text(req.fragor)}\n\n"
        f"Samtal:\n{transcript}\n\n"
        "Returnera JSON-mappningen nu."
    )
    try:
        _, reply = await _run_query(
            prompt=prompt,
            system_prompt=EXTRACT_SYSTEM_PROMPT,
            resume_id=None,
            model=MODEL_EXTRACT_API,
        )
        svar = json.loads(_strip_json_fences(reply))
        if not isinstance(svar, dict):
            raise ValueError("not a dict")
    except Exception:
        logger.exception("extract failed for token %s", req.fastighet_token)
        return {"svar": None}
    return {"svar": svar}
