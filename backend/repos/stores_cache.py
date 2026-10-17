"""Key/value cache of the store directories and town coordinates (table stores_cache, P4)."""

import time

from backend.database import get_db


async def get(key: str, max_age: float | None = None, now: float | None = None) -> tuple[str, float] | None:
    """``(value, saved_at)`` of ``key``, or None when missing or older than ``max_age`` seconds."""
    db = await get_db()
    cursor = await db.execute("SELECT value, saved_at FROM stores_cache WHERE key = ?", (key,))
    row = await cursor.fetchone()
    if row is None:
        return None
    if max_age is not None and (now or time.time()) - row["saved_at"] > max_age:
        return None
    return row["value"], row["saved_at"]


async def put(key: str, value: str, now: float | None = None) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO stores_cache (key, value, saved_at) VALUES (?, ?, ?)", (key, value, now or time.time())
    )
    await db.commit()


async def delete(key: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM stores_cache WHERE key = ?", (key,))
    await db.commit()
