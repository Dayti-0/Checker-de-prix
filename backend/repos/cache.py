"""Search cache: the products found for (retailer, store, query) (area of P3)."""

import json
import time

from backend import config
from backend.database import get_db


async def get_cached_entry(cache_key: str) -> tuple[list[dict], float] | None:
    """(products, time they were saved) of a fresh entry, else None (expired ones are removed)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT results_json, created_at FROM search_cache WHERE cache_key = ?",
        (cache_key,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    if time.time() - row["created_at"] > config.CACHE_TTL_SECONDS:
        await db.execute("DELETE FROM search_cache WHERE cache_key = ?", (cache_key,))
        await db.commit()
        return None
    return json.loads(row["results_json"]), row["created_at"]


async def get_cached(cache_key: str) -> list[dict] | None:
    entry = await get_cached_entry(cache_key)
    return entry[0] if entry else None


async def set_cached(cache_key: str, results: list[dict]) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO search_cache (cache_key, results_json, created_at) VALUES (?, ?, ?)",
        (cache_key, json.dumps(results), time.time()),
    )
    await db.commit()


async def clear_cache(prefix: str = "") -> None:
    db = await get_db()
    await db.execute("DELETE FROM search_cache WHERE cache_key LIKE ?", (prefix + "%",))
    await db.commit()
