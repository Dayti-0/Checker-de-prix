import json
import time

import aiosqlite

from backend import config

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(config.DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _init_tables(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS search_cache (
            cache_key TEXT PRIMARY KEY,
            results_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shopping_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            picks_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL
        );
    """)
    # Tables from the first version of the app are no longer used
    await db.execute("DROP TABLE IF EXISTS app_config")
    await db.commit()


# --- Search cache ---


async def get_cached(cache_key: str) -> list[dict] | None:
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
    return json.loads(row["results_json"])


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


# --- Settings (JSON values) ---


async def get_setting(key: str) -> str | None:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    await db.commit()


# --- Shopping list ---


def _row_to_item(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "query": row["query"],
        "quantity": row["quantity"],
        "picks": json.loads(row["picks_json"]),
    }


async def list_items() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM shopping_list ORDER BY id")
    return [_row_to_item(r) for r in await cursor.fetchall()]


async def get_item(item_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM shopping_list WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    return _row_to_item(row) if row else None


async def insert_item(query: str, quantity: int, picks: dict) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO shopping_list (query, quantity, picks_json, created_at) VALUES (?, ?, ?, ?)",
        (query, quantity, json.dumps(picks), time.time()),
    )
    await db.commit()
    return cursor.lastrowid


async def update_item(item_id: int, quantity: int, picks: dict) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE shopping_list SET quantity = ?, picks_json = ? WHERE id = ?",
        (quantity, json.dumps(picks), item_id),
    )
    await db.commit()


async def delete_item(item_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
    await db.commit()


async def clear_items() -> None:
    db = await get_db()
    await db.execute("DELETE FROM shopping_list")
    await db.commit()
