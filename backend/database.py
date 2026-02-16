import json
import time

import aiosqlite

from backend.config import CACHE_TTL_SECONDS, DB_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _init_tables(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS search_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            store TEXT NOT NULL,
            results_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(query, store)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    await db.commit()


async def get_cached_results(query: str, store: str) -> list[dict] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT results_json, created_at FROM search_cache WHERE query = ? AND store = ?",
        (query.lower().strip(), store),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    if time.time() - row["created_at"] > CACHE_TTL_SECONDS:
        await db.execute(
            "DELETE FROM search_cache WHERE query = ? AND store = ?",
            (query.lower().strip(), store),
        )
        await db.commit()
        return None
    return json.loads(row["results_json"])


async def set_cached_results(query: str, store: str, results: list[dict]) -> None:
    db = await get_db()
    await db.execute(
        """INSERT OR REPLACE INTO search_cache (query, store, results_json, created_at)
           VALUES (?, ?, ?, ?)""",
        (query.lower().strip(), store, json.dumps(results), time.time()),
    )
    await db.commit()


async def get_config(key: str) -> str | None:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM app_config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else None


async def set_config(key: str, value: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)",
        (key, value),
    )
    await db.commit()
