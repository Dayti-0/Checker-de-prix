"""P5: usual items, saved lists (templates), version of the list, last basket."""


async def up(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS list_history (
            query_key TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            last_added_at REAL NOT NULL
        )""")
    # Each line already in the list counts as one addition
    await db.execute("""
        INSERT OR IGNORE INTO list_history (query_key, query, count, last_added_at)
        SELECT query_key, query, 1, created_at FROM shopping_list WHERE query_key IS NOT NULL""")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            items_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )""")
    await db.execute("CREATE TABLE IF NOT EXISTS list_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
    await db.execute("INSERT OR IGNORE INTO list_meta (key, value) VALUES ('version', 0)")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS basket_last (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            comparison_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )""")
