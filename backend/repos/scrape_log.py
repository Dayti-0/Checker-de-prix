"""Journal of the searches at each retailer (table scrape_log, area of P4)."""

import time

from backend.database import get_db

COLUMNS = (
    "ts",
    "store",
    "store_ctx",
    "query",
    "status",
    "source",
    "products",
    "priced",
    "elapsed_ms",
    "error",
    "from_cache",
)


async def insert(entry: dict) -> None:
    db = await get_db()
    values = [entry.get(column) for column in COLUMNS]
    await db.execute(
        f"INSERT INTO scrape_log ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",  # noqa: S608
        values,
    )
    await db.commit()


async def entries(since: float = 0, store: str | None = None, limit: int = 2000, real_only: bool = False) -> list[dict]:
    """Rows newer than ``since``, the newest first (``real_only``: not from the cache)."""
    db = await get_db()
    query = "SELECT * FROM scrape_log WHERE ts >= ?"
    params: list = [since]
    if store:
        query += " AND store = ?"
        params.append(store)
    if real_only:
        query += " AND from_cache = 0"
    query += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(limit)
    cursor = await db.execute(query, params)
    return [dict(row) for row in await cursor.fetchall()]


async def totals(store: str, week_since: float, since: float) -> dict:
    """Figures of retailer ``store`` over its whole journal, searches read on the site only.

    ``searches_7d``, ``ok_7d``, ``avg_elapsed_ms``: since ``week_since``, the
    answers « Magasin à choisir » left out; ``last_success`` and ``last_source``:
    the newest search that worked since ``since``.
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*), COALESCE(SUM(status = 'ok'), 0), AVG(NULLIF(elapsed_ms, 0)) FROM scrape_log"
        " WHERE store = ? AND from_cache = 0 AND ts >= ? AND status != 'store_required'",
        (store, week_since),
    )
    count, ok, avg = await cursor.fetchone()
    cursor = await db.execute(
        "SELECT ts, source FROM scrape_log WHERE store = ? AND from_cache = 0 AND status = 'ok' AND ts >= ?"
        " ORDER BY ts DESC, id DESC LIMIT 1",
        (store, since),
    )
    last = await cursor.fetchone()
    return {
        "searches_7d": count,
        "ok_7d": ok,
        "avg_elapsed_ms": round(avg) if avg is not None else None,
        "last_success": last[0] if last else None,
        "last_source": last[1] if last else None,
    }


async def purge(max_age_seconds: float, now: float | None = None) -> int:
    """Delete the rows older than ``max_age_seconds``; returns how many."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM scrape_log WHERE ts < ?", ((now or time.time()) - max_age_seconds,))
    await db.commit()
    return cursor.rowcount or 0


async def clear() -> None:
    db = await get_db()
    await db.execute("DELETE FROM scrape_log")
    await db.commit()
