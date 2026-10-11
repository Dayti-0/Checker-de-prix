"""P5: lines deleted lately, kept for « Annuler » (POST /api/list/restore).

The page sends only the ids of the deleted lines: they come back exactly as the
server saved them (choices with their verified prices, ticks, date of addition).
"""


async def up(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS list_trash (
            id INTEGER PRIMARY KEY,
            item_json TEXT NOT NULL,
            deleted_at REAL NOT NULL
        )""")
