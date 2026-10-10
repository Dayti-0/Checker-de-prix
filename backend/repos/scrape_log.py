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


async def entries(since: float = 0, store: str | None = None, limit: int = 2000) -> list[dict]:
    """Rows newer than ``since``, the newest first."""
    db = await get_db()
    query = "SELECT * FROM scrape_log WHERE ts >= ?"
    params: list = [since]
    if store:
        query += " AND store = ?"
        params.append(store)
    query += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(limit)
    cursor = await db.execute(query, params)
    return [dict(row) for row in await cursor.fetchall()]


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
