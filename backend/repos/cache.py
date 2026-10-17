"""Search cache: the products found for (retailer, store, query) (area of P3).

Rows of the ``search_cache`` table: ``results_json`` is the list of products
(PrixMalin 2.0) or ``{"products": [...], "source": "api"}``; ``created_at`` is
the time of the search on the site. Reading never deletes anything: how old an
entry may be is decided by services/search.py (fresh 6 h, « no product » 30 min,
older prices shown when the site fails, up to 7 days). ``purge_cache`` removes
the entries older than 7 days (at startup, then every day).
"""

import json
import time
from typing import NamedTuple

from backend import config
from backend.database import get_db


class CacheEntry(NamedTuple):
    """A cached search: ``entry[0]`` is the list of products, ``entry[1]`` the time of the search."""

    products: list[dict]
    created_at: float
    source: str | None = None


def decode(results_json: str, created_at: float) -> CacheEntry | None:
    """Entry of a row, or None when the row is unreadable (pure function)."""
    try:
        data = json.loads(results_json)
    except (TypeError, ValueError):
        return None
    source = None
    if isinstance(data, dict):
        source = data.get("source") if isinstance(data.get("source"), str) else None
        data = data.get("products")
    if not isinstance(data, list) or not all(isinstance(p, dict) for p in data):
        return None
    return CacheEntry(data, float(created_at), source)


async def get_entry(cache_key: str, max_age: float | None = None, now: float | None = None) -> CacheEntry | None:
    """The cached search of ``cache_key`` younger than ``max_age`` seconds (any age when None)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT results_json, created_at FROM search_cache WHERE cache_key = ?",
        (cache_key,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    entry = decode(row["results_json"], row["created_at"])
    if entry is None:
        return None
    now = time.time() if now is None else now
    if max_age is not None and now - entry.created_at > max_age:
        return None
    return entry


async def get_cached_entry(cache_key: str) -> CacheEntry | None:
    """``(products, created_at, source)`` of an entry younger than 6 hours, else None."""
    return await get_entry(cache_key, config.CACHE_TTL_SECONDS)


async def get_cached(cache_key: str) -> tuple[list[dict], float] | None:
    """``(products, created_at)`` of an entry younger than 6 hours, else None (nothing deleted)."""
    entry = await get_cached_entry(cache_key)
    return (entry.products, entry.created_at) if entry else None


async def set_cached(
    cache_key: str, results: list[dict], *, source: str | None = None, created_at: float | None = None
) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO search_cache (cache_key, results_json, created_at) VALUES (?, ?, ?)",
        (
            cache_key,
            json.dumps({"products": results, "source": source}),
            time.time() if created_at is None else created_at,
        ),
    )
    await db.commit()


async def clear_cache(prefix: str = "") -> None:
    """Remove the entries whose key starts with ``prefix`` (``"aldi|"``: one retailer; ``""``: all)."""
    db = await get_db()
    pattern = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    await db.execute("DELETE FROM search_cache WHERE cache_key LIKE ? ESCAPE '\\'", (pattern,))
    await db.commit()


async def purge_cache(max_age: float | None = None, now: float | None = None) -> int:
    """Remove the entries older than ``max_age`` (default 7 days); returns how many."""
    max_age = config.CACHE_STALE_MAX_SECONDS if max_age is None else max_age
    now = time.time() if now is None else now
    db = await get_db()
    cursor = await db.execute("DELETE FROM search_cache WHERE created_at < ?", (now - max_age,))
    await db.commit()
    return cursor.rowcount or 0
