"""The three tables of PrixMalin 2.0 (nothing changes on a database that has them)."""


async def up(db) -> None:
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
        -- Table of the first version of the app, no longer used
        DROP TABLE IF EXISTS app_config;
    """)
