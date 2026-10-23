"""Saved lists (« listes modèles ») such as « Courses de la semaine » (area of P5)."""

import json
import time

import aiosqlite

from backend.database import get_db
from backend.repos.shopping_list import writing


def _items(text: str) -> list[dict]:
    try:
        items = json.loads(text)
    except ValueError:
        return []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _row(row: aiosqlite.Row, with_items: bool = False) -> dict:
    items = _items(row["items_json"])
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


async def all_templates() -> list[dict]:
    """Every template with its items (backups)."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM templates ORDER BY id")
    return [_row(r, with_items=True) for r in await cursor.fetchall()]


async def save_template(name: str, items: list[dict], *, db: aiosqlite.Connection | None = None) -> int:
    """Save ``items`` under ``name`` (a template of that name, in any case, is replaced); returns its id."""
    now = time.time()
    async with writing(db) as tx:
        await tx.execute(
            "INSERT INTO templates (name, items_json, created_at, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET items_json = excluded.items_json, updated_at = excluded.updated_at",
            (name, json.dumps(items), now, now),
        )
        cursor = await tx.execute("SELECT id FROM templates WHERE name = ?", (name,))
        row = await cursor.fetchone()
        return row[0]


async def find_by_name(name: str) -> dict | None:
    """The template called ``name`` in any case (the column is COLLATE NOCASE)."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM templates WHERE name = ?", (name,))
    row = await cursor.fetchone()
    return _row(row) if row else None


async def delete_template(template_id: int, now: float, max_age: float) -> bool:
    """Delete a template, kept ``max_age`` seconds for « Annuler » (restore_template)."""
    async with writing() as tx:
        cursor = await tx.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
        row = await cursor.fetchone()
        if row is None:
            return False
        await tx.execute("DELETE FROM template_trash WHERE deleted_at < ?", (now - max_age,))
        await tx.execute(
            "INSERT OR REPLACE INTO template_trash (id, template_json, deleted_at) VALUES (?, ?, ?)",
            (template_id, json.dumps({k: row[k] for k in row.keys()}), now),
        )
        await tx.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        return True


async def restore_template(template_id: int, since: float) -> int | None:
    """Put back the template ``template_id`` deleted after ``since``; returns its id, None when
    it is not kept any more. Raises ``NameTaken`` when a template has its name meanwhile."""
    async with writing() as tx:
        cursor = await tx.execute(
            "SELECT template_json FROM template_trash WHERE id = ? AND deleted_at >= ?", (template_id, since)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        saved = json.loads(row[0])
        cursor = await tx.execute("SELECT id FROM templates WHERE name = ?", (saved["name"],))
        if await cursor.fetchone() is not None:
            raise NameTaken(saved["name"])
        cursor = await tx.execute("SELECT id FROM templates WHERE id = ?", (template_id,))
        taken = await cursor.fetchone() is not None
        cursor = await tx.execute(
            "INSERT INTO templates (id, name, items_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                None if taken else template_id,
                saved["name"],
                saved["items_json"],
                saved["created_at"],
                saved["updated_at"],
            ),
        )
        await tx.execute("DELETE FROM template_trash WHERE id = ?", (template_id,))
        return cursor.lastrowid


class NameTaken(Exception):
    """A template has the name of the one put back."""


async def clear_templates(*, db: aiosqlite.Connection | None = None) -> None:
    async with writing(db) as tx:
        await tx.execute("DELETE FROM templates")
