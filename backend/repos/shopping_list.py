"""Lines of the shopping list (area of P5)."""

import json
import time

import aiosqlite

from backend.database import get_db


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
