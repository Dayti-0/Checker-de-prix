"""Journal of the searches at each retailer, for the page « État des enseignes » (P4)."""


async def up(db) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            store TEXT NOT NULL,
            store_ctx TEXT NOT NULL DEFAULT '',
            query TEXT NOT NULL,
            status TEXT NOT NULL,
            source TEXT,
            products INTEGER NOT NULL DEFAULT 0,
            priced INTEGER NOT NULL DEFAULT 0,
            elapsed_ms INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            from_cache INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS scrape_log_store_ts ON scrape_log (store, ts);
    """)
