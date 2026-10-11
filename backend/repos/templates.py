"""Saved lists (« listes modèles ») such as « Courses de la semaine » (area of P5)."""

import json
import time

import aiosqlite

from backend.database import get_db


def _row(row: aiosqlite.Row, with_items: bool = False) -> dict:
    items = json.loads(row["items_json"])
    data = {
        "id": row["id"],
        "name": row["name"],
        "item_count": len(items),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if with_items:
        data["items"] = items
    return data


async def list_templates() -> list[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM templates ORDER BY name COLLATE NOCASE")
    return [_row(r) for r in await cursor.fetchall()]


async def get_template(template_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
    row = await cursor.fetchone()
    return _row(row, with_items=True) if row else None


async def save_template(name: str, items: list[dict]) -> int:
    """Save ``items`` under ``name`` (an existing template of that name is replaced)."""
    db = await get_db()
    now = time.time()
    await db.execute(
        "INSERT INTO templates (name, items_json, created_at, updated_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(name) DO UPDATE SET items_json = excluded.items_json, updated_at = excluded.updated_at",
        (name, json.dumps(items), now, now),
    )
    await db.commit()
    cursor = await db.execute("SELECT id FROM templates WHERE name = ?", (name,))
    row = await cursor.fetchone()
    return row[0]


async def delete_template(template_id: int) -> bool:
    db = await get_db()
    cursor = await db.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    await db.commit()
    return cursor.rowcount > 0


async def clear_templates() -> None:
    db = await get_db()
    await db.execute("DELETE FROM templates")
    await db.commit()
