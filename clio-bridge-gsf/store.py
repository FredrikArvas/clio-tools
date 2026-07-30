import asyncio
import time
from dataclasses import dataclass

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    fastighet_token TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turns INTEGER NOT NULL DEFAULT 0,
    namn TEXT NOT NULL DEFAULT '',
    fragor_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);
"""


@dataclass
class SessionRow:
    fastighet_token: str
    session_id: str
    turns: int
    namn: str
    fragor_json: str
    updated_at: str


class SessionStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._token_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def init(self):
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(SCHEMA)
            await db.commit()

    async def lock_for(self, token: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._token_locks.get(token)
            if lock is None:
                lock = asyncio.Lock()
                self._token_locks[token] = lock
            return lock

    async def get(self, token: str) -> SessionRow | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT fastighet_token, session_id, turns, namn, fragor_json, updated_at "
                "FROM sessions WHERE fastighet_token = ?",
                (token,),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return SessionRow(**dict(row))

    async def upsert(self, token: str, session_id: str, turns: int, namn: str, fragor_json: str):
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO sessions (fastighet_token, session_id, turns, namn, fragor_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(fastighet_token) DO UPDATE SET "
                "session_id=excluded.session_id, turns=excluded.turns, updated_at=excluded.updated_at",
                (token, session_id, turns, namn, fragor_json, now),
            )
            await db.commit()

    async def delete(self, token: str):
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM sessions WHERE fastighet_token = ?", (token,))
            await db.commit()

    async def count(self) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM sessions")
            (n,) = await cur.fetchone()
            return n

    async def purge_stale(self, max_age_days: int) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "DELETE FROM sessions WHERE updated_at < datetime('now', ?)",
                (f"-{max_age_days} days",),
            )
            await db.commit()
            return cur.rowcount
