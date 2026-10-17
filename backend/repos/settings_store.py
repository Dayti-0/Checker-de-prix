"""Key/value settings stored as JSON text (area of P4; ``pref:*`` keys belong to prefs)."""

from backend.database import get_db


async def get_setting(key: str) -> str | None:
    db = await get_db()
    cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    await db.commit()


async def delete_setting(key: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM settings WHERE key = ?", (key,))
    await db.commit()


async def all_settings() -> dict[str, str]:
    db = await get_db()
    cursor = await db.execute("SELECT key, value FROM settings ORDER BY key")
    return {row["key"]: row["value"] for row in await cursor.fetchall()}
