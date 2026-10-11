"""Lines of the shopping list, usual items, version of the list, last basket (area of P5).

Every write to the list increments its version (``get_version``), which the
pages poll to follow the changes made on another device.
"""

import json
import re
import time
import unicodedata

import aiosqlite

from backend.database import get_db

# Columns that update_fields() may change, with their conversion to SQLite
_FIELDS = {
    "query": lambda v: v,
    "query_key": lambda v: v,
    "quantity": int,
    "picks": lambda v: json.dumps(v),
    "target": lambda v: v,
    "category": lambda v: v,
    "note": lambda v: v,
    "compare": lambda v: 1 if v else 0,
    "excluded": lambda v: json.dumps(sorted(set(v))),
    "checked": lambda v: 1 if v else 0,
    "checked_at": lambda v: v,
}
_COLUMNS = {"picks": "picks_json", "excluded": "excluded_json"}


def list_key(query: str) -> str:
    """Normalised query: one line per key (« Farine » and « farine » are the same item).

    Stable: the keys of existing lines are computed with it (UNIQUE index).
    """
    text = (query or "").lower().replace("œ", "oe").replace("æ", "ae")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _row_to_item(row: aiosqlite.Row) -> dict:
    keys = row.keys()

    def get(name, default=None):
        return row[name] if name in keys and row[name] is not None else default

    return {
        "id": row["id"],
        "query": row["query"],
        "quantity": row["quantity"],
        "picks": json.loads(row["picks_json"] or "{}"),
        "target": get("target"),
        "category": get("category"),
        "note": get("note"),
        "compare": bool(get("compare", 1)),
        "excluded": json.loads(get("excluded_json", "[]")),
        "checked": bool(get("checked", 0)),
        "checked_at": get("checked_at"),
    }


async def _bump(db: aiosqlite.Connection) -> None:
    await db.execute("UPDATE list_meta SET value = value + 1 WHERE key = 'version'")


async def _commit(db: aiosqlite.Connection) -> None:
    await _bump(db)
    await db.commit()


async def get_version() -> int:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM list_meta WHERE key = 'version'")
    row = await cursor.fetchone()
    if row is None:  # emptied by hand: start again
        await db.execute("INSERT OR IGNORE INTO list_meta (key, value) VALUES ('version', 0)")
        await db.commit()
        return 0
    return row[0]


async def list_items() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM shopping_list ORDER BY id")
    return [_row_to_item(r) for r in await cursor.fetchall()]


async def count_items() -> int:
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM shopping_list")
    row = await cursor.fetchone()
    return row[0]


async def get_item(item_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM shopping_list WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    return _row_to_item(row) if row else None


async def get_by_key(key: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM shopping_list WHERE query_key = ?", (key,))
    row = await cursor.fetchone()
    return _row_to_item(row) if row else None


async def insert_item(
    query: str,
    quantity: int,
    picks: dict,
    *,
    item_id: int | None = None,
    target: str | None = None,
    category: str | None = None,
    note: str | None = None,
    compare: bool = True,
    excluded: list[str] | tuple = (),
    checked: bool = False,
    checked_at: float | None = None,
) -> int:
    """Insert a line (with ``item_id`` to put a deleted line back); returns its id."""
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO shopping_list (id, query, query_key, quantity, picks_json, target, category, note, compare,"
        " excluded_json, checked, checked_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item_id,
            query,
            list_key(query),
            quantity,
            json.dumps(picks),
            target,
            category,
            note,
            1 if compare else 0,
            json.dumps(sorted(set(excluded))),
            1 if checked else 0,
            checked_at,
            time.time(),
        ),
    )
    await _commit(db)
    return cursor.lastrowid


async def update_item(item_id: int, quantity: int, picks: dict) -> None:
    await update_fields(item_id, quantity=quantity, picks=picks)


async def update_fields(item_id: int, **fields) -> None:
    """Change some columns of a line (names of _FIELDS)."""
    if not fields:
        return
    if "query" in fields:
        fields["query_key"] = list_key(fields["query"])
    sets, values = [], []
    for name, value in fields.items():
        convert = _FIELDS[name]
        sets.append(f"{_COLUMNS.get(name, name)} = ?")
        values.append(None if value is None else convert(value))
    db = await get_db()
    await db.execute(f"UPDATE shopping_list SET {', '.join(sets)} WHERE id = ?", (*values, item_id))  # noqa: S608
    await _commit(db)


async def delete_item(item_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
    await _commit(db)


async def clear_items() -> None:
    db = await get_db()
    await db.execute("DELETE FROM shopping_list")
    await _commit(db)


async def delete_checked() -> int:
    db = await get_db()
    cursor = await db.execute("DELETE FROM shopping_list WHERE checked = 1")
    await _commit(db)
    return cursor.rowcount


async def uncheck_all() -> None:
    db = await get_db()
    await db.execute("UPDATE shopping_list SET checked = 0, checked_at = NULL")
    await _commit(db)


# --- Usual items ---------------------------------------------------------------


async def record_added(query: str) -> None:
    """One more addition of ``query`` to the list (usual items: at least 2)."""
    db = await get_db()
    await db.execute(
        "INSERT INTO list_history (query_key, query, count, last_added_at) VALUES (?, ?, 1, ?)"
        " ON CONFLICT(query_key) DO UPDATE SET count = count + 1, query = excluded.query,"
        " last_added_at = excluded.last_added_at",
        (list_key(query), query, time.time()),
    )
    await db.commit()


async def usual_items(min_count: int = 2, limit: int = 12) -> list[dict]:
    """Queries added at least ``min_count`` times and not in the list, most frequent first."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT query, count FROM list_history WHERE count >= ?"
        " AND query_key NOT IN (SELECT query_key FROM shopping_list WHERE query_key IS NOT NULL)"
        " ORDER BY count DESC, last_added_at DESC LIMIT ?",
        (min_count, limit),
    )
    return [{"query": r["query"], "count": r["count"]} for r in await cursor.fetchall()]


async def clear_history() -> None:
    db = await get_db()
    await db.execute("DELETE FROM list_history")
    await db.commit()


# --- Last basket comparison ----------------------------------------------------


async def save_last_basket(comparison: dict) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO basket_last (id, comparison_json, created_at) VALUES (1, ?, ?)",
        (json.dumps(comparison), time.time()),
    )
    await db.commit()


async def get_last_basket() -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT comparison_json FROM basket_last WHERE id = 1")
    row = await cursor.fetchone()
    return json.loads(row[0]) if row else None
