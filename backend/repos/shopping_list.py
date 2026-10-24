"""Lines of the shopping list, usual items, version of the list, last basket (area of P5).

Every write to the list increments its version (``get_version``) in the same
transaction: the pages poll it to follow the changes made on another device.
A write function takes ``db``, the connection of a transaction already open
(``async with database.transaction() as db``), to be written with other
statements all at once; without it, it opens its own transaction.
"""

import contextlib
import json
import time
from collections.abc import AsyncIterator

import aiosqlite

from backend.database import get_db, transaction
from backend.services.matching import query_key

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

    It is ``matching.query_key``, which the page also uses (``listKey`` of
    add-sheet.js). The keys of the saved lines are computed with it (UNIQUE
    index): if query_key changes, a migration must compute them again.
    A query without a Latin letter or digit (« 🍌 ») has the key "": the
    services refuse it, and a line kept from before is saved without a key
    (``_stored_key``: NULL, never merged with another one).
    """
    return query_key(query or "")


def _stored_key(query: str) -> str | None:
    """The key written in the column ``query_key``: NULL rather than "" (the UNIQUE index
    lets several lines have no key, they are never merged)."""
    return list_key(query) or None


@contextlib.asynccontextmanager
async def writing(db: aiosqlite.Connection | None = None) -> AsyncIterator[aiosqlite.Connection]:
    """``db`` (a transaction already open), or a new transaction."""
    if db is not None:
        yield db
        return
    async with transaction() as tx:
        yield tx


def _json(text: str | None, default):
    try:
        value = json.loads(text) if text else default
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def _row_to_item(row: aiosqlite.Row) -> dict:
    keys = row.keys()

    def get(name, default=None):
        return row[name] if name in keys and row[name] is not None else default

    return {
        "id": row["id"],
        "query": row["query"],
        "key": get("query_key") or list_key(row["query"]),
        "quantity": row["quantity"],
        "picks": _json(row["picks_json"], {}),
        "target": get("target"),
        "category": get("category"),
        "note": get("note"),
        "compare": bool(get("compare", 1)),
        "excluded": _json(get("excluded_json"), []),
        "checked": bool(get("checked", 0)),
        "checked_at": get("checked_at"),
        "created_at": get("created_at"),
    }


async def _bump(db: aiosqlite.Connection) -> None:
    await db.execute(
        "INSERT INTO list_meta (key, value) VALUES ('version', 1) ON CONFLICT(key) DO UPDATE SET value = value + 1"
    )


async def get_version() -> int:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM list_meta WHERE key = 'version'")
    row = await cursor.fetchone()
    return row[0] if row else 0


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
    if not key:
        return None  # lines without a key are never the same item
    db = await get_db()
    cursor = await db.execute("SELECT * FROM shopping_list WHERE query_key = ?", (key,))
    row = await cursor.fetchone()
    return _row_to_item(row) if row else None


async def insert_item(
    query: str,
    quantity: int,
    picks: dict,
    *,
    db: aiosqlite.Connection | None = None,
    item_id: int | None = None,
    target: str | None = None,
    category: str | None = None,
    note: str | None = None,
    compare: bool = True,
    excluded: list[str] | tuple = (),
    checked: bool = False,
    checked_at: float | None = None,
    created_at: float | None = None,
) -> int:
    """Insert a line (with ``item_id`` and ``created_at`` to put a deleted line back); returns its id."""
    async with writing(db) as tx:
        cursor = await tx.execute(
            "INSERT INTO shopping_list (id, query, query_key, quantity, picks_json, target, category, note, compare,"
            " excluded_json, checked, checked_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                query,
                _stored_key(query),
                quantity,
                json.dumps(picks),
                target,
                category,
                note,
                1 if compare else 0,
                json.dumps(sorted(set(excluded))),
                1 if checked else 0,
                checked_at,
                time.time() if created_at is None else created_at,
            ),
        )
        await _bump(tx)
        return cursor.lastrowid


async def update_item(item_id: int, quantity: int, picks: dict) -> None:
    await update_fields(item_id, quantity=quantity, picks=picks)


async def update_fields(item_id: int, *, db: aiosqlite.Connection | None = None, **fields) -> None:
    """Change some columns of a line (names of _FIELDS)."""
    if not fields:
        return
    if "query" in fields:
        fields["query_key"] = _stored_key(fields["query"])
    sets, values = [], []
    for name, value in fields.items():
        convert = _FIELDS[name]
        sets.append(f"{_COLUMNS.get(name, name)} = ?")
        values.append(None if value is None else convert(value))
    async with writing(db) as tx:
        await tx.execute(f"UPDATE shopping_list SET {', '.join(sets)} WHERE id = ?", (*values, item_id))  # noqa: S608
        await _bump(tx)


async def delete_item(item_id: int, *, db: aiosqlite.Connection | None = None) -> bool:
    async with writing(db) as tx:
        cursor = await tx.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
        await _bump(tx)
        return cursor.rowcount > 0


async def clear_items(*, db: aiosqlite.Connection | None = None) -> None:
    async with writing(db) as tx:
        await tx.execute("DELETE FROM shopping_list")
        await _bump(tx)


async def delete_items(ids: list[int], *, db: aiosqlite.Connection | None = None) -> int:
    """Delete the lines ``ids``; returns how many were deleted."""
    if not ids:
        return 0
    marks = ", ".join("?" for _ in ids)
    async with writing(db) as tx:
        cursor = await tx.execute(f"DELETE FROM shopping_list WHERE id IN ({marks})", tuple(ids))  # noqa: S608
        await _bump(tx)
        return cursor.rowcount


async def uncheck_all(now: float, *, db: aiosqlite.Connection | None = None) -> None:
    """Untick everything, dated ``now``: a tick made earlier (offline on a phone) and sent
    later loses against it (the most recent tick wins)."""
    async with writing(db) as tx:
        await tx.execute("UPDATE shopping_list SET checked = 0, checked_at = ?", (now,))
        await _bump(tx)


# --- Deleted lines (« Annuler ») -------------------------------------------------


async def trash_items(items: list[dict], now: float, max_age: float, *, db: aiosqlite.Connection) -> None:
    """Keep the deleted lines ``items`` (as read by list_items) for « Annuler »; forget
    those deleted more than ``max_age`` seconds ago. In the transaction ``db``."""
    await db.execute("DELETE FROM list_trash WHERE deleted_at < ?", (now - max_age,))
    for item in items:
        await db.execute(
            "INSERT OR REPLACE INTO list_trash (id, item_json, deleted_at) VALUES (?, ?, ?)",
            (item["id"], json.dumps(item), now),
        )


async def trashed_items(ids: list[int], since: float) -> list[dict]:
    """The lines ``ids`` deleted after ``since`` (in the order of ``ids``)."""
    if not ids:
        return []
    db = await get_db()
    marks = ", ".join("?" for _ in ids)
    cursor = await db.execute(
        f"SELECT id, item_json FROM list_trash WHERE deleted_at >= ? AND id IN ({marks})",  # noqa: S608
        (since, *ids),
    )
    rows = {row["id"]: _json(row["item_json"], {}) for row in await cursor.fetchall()}
    return [rows[i] for i in ids if rows.get(i)]


async def untrash(ids: list[int], *, db: aiosqlite.Connection) -> None:
    for item_id in ids:
        await db.execute("DELETE FROM list_trash WHERE id = ?", (item_id,))


# --- Usual items ---------------------------------------------------------------


async def record_added(query: str, *, db: aiosqlite.Connection | None = None) -> None:
    """One more addition of ``query`` to the list (usual items: at least 2)."""
    if not list_key(query):
        return  # no key: never a usual item
    async with writing(db) as tx:
        await tx.execute(
            "INSERT INTO list_history (query_key, query, count, last_added_at) VALUES (?, ?, 1, ?)"
            " ON CONFLICT(query_key) DO UPDATE SET count = count + 1, query = excluded.query,"
            " last_added_at = excluded.last_added_at",
            (list_key(query), query, time.time()),
        )


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


async def history_rows() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT query, count, last_added_at FROM list_history ORDER BY query_key")
    return [dict(r) for r in await cursor.fetchall()]


async def replace_history(rows: list[dict]) -> None:
    """Replace the usual items with ``rows`` ({query, count, last_added_at}), all at once."""
    async with transaction() as db:
        await db.execute("DELETE FROM list_history")
        for row in rows:
            await db.execute(
                "INSERT INTO list_history (query_key, query, count, last_added_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(query_key) DO UPDATE SET count = count + excluded.count",
                (list_key(row["query"]), row["query"], int(row["count"]), float(row.get("last_added_at") or 0)),
            )


async def forget_usual(query: str) -> bool:
    """« Ne plus proposer » a usual item."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM list_history WHERE query_key = ?", (list_key(query),))
    return cursor.rowcount > 0


# --- Last basket comparison ----------------------------------------------------


async def save_last_basket(comparison: dict, list_version: int | None = None) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO basket_last (id, comparison_json, created_at, list_version) VALUES (1, ?, ?, ?)",
        (json.dumps(comparison), time.time(), list_version),
    )


async def get_last_basket() -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT comparison_json FROM basket_last WHERE id = 1")
    row = await cursor.fetchone()
    if row is None:
        return None
    return _json(row[0], {}) or None


async def clear_last_basket() -> None:
    db = await get_db()
    await db.execute("DELETE FROM basket_last")
