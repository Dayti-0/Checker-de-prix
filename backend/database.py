"""The SQLite database: one shared connection, WAL journal, named migrations.

The tables are created and changed by the migrations of ``backend/migrations/``.
The queries live in ``backend/repos/`` (one module per area); they are also
reachable from here, e.g. ``database.get_cached(...)``, as before the split.
"""

import asyncio
import importlib

import aiosqlite

from backend import config, migrations

_db: aiosqlite.Connection | None = None
_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None

# Functions of backend/repos/ re-exported by this module
_REPO_FUNCTIONS = {
    "cache": ("get_cached", "get_cached_entry", "set_cached", "clear_cache"),
    "settings_store": ("get_setting", "set_setting", "delete_setting", "all_settings"),
    "shopping_list": (
        "list_items",
        "get_item",
        "insert_item",
        "update_item",
        "delete_item",
        "clear_items",
        "count_items",
    ),
}
_REEXPORTS = {name: module for module, names in _REPO_FUNCTIONS.items() for name in names}


def __getattr__(name: str):
    # Imported on first use: the repos themselves import get_db from here
    module = _REEXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"backend.repos.{module}"), name)


def __dir__() -> list[str]:
    return sorted([*globals(), *_REEXPORTS])


def _open_lock() -> asyncio.Lock:
    """A lock of the running loop (each test runs its own loop)."""
    global _lock
    loop = asyncio.get_running_loop()
    if _lock is None or _lock[0] is not loop:
        _lock = (loop, asyncio.Lock())
    return _lock[1]


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is not None:
        return _db
    async with _open_lock():
        if _db is None:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            db = await aiosqlite.connect(config.DB_PATH)
            try:
                db.row_factory = aiosqlite.Row
                # Wait for another connection (a test, a backup) instead of failing
                await db.execute("PRAGMA busy_timeout = 5000")
                # Readers no longer block the writer
                await db.execute("PRAGMA journal_mode = WAL")
                await migrations.apply(db, config.DB_PATH)
            except BaseException:
                await db.close()
                raise
            _db = db
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        db, _db = _db, None
        await db.close()
