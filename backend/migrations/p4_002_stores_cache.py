"""Cache of the store directories and of the town coordinates (P4).

Not part of the backups: everything in it can be downloaded again.
"""


async def up(db) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS stores_cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            saved_at REAL NOT NULL
        );
    """)
