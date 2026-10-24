"""Named migrations of the SQLite database.

Each module ``pN_NNN_<slug>.py`` of this package defines ``async def up(db)``
(``db``: an aiosqlite connection). The modules are applied once each, in the
alphabetical order of their name (their id), and recorded in the table
``schema_migrations(id, applied_at)``. Before applying migrations to a
database that already holds tables, a copy is saved next to it
(``prixmalin.db.bak``).

A migration never changes once merged: to change a table, add a new module.
"""

import logging
import pkgutil
import re
import time
from importlib import import_module
from pathlib import Path

logger = logging.getLogger("prixmalin.migrations")

_NAME = re.compile(r"^p\d+_\d{3}_\w+$")


def available() -> list[str]:
    """Ids of every migration of the package, in the order they are applied."""
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if _NAME.match(m.name))


def backup_path(db_path: Path) -> Path:
    return Path(db_path).with_name(Path(db_path).name + ".bak")


async def _tables(db) -> set[str]:
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    return {row[0] for row in await cursor.fetchall()}


async def _backup(db, db_path: Path) -> None:
    target = backup_path(db_path)
    target.unlink(missing_ok=True)
    await db.execute("VACUUM INTO ?", (str(target),))
    logger.info("Database saved in %s before the migrations", target)


async def apply(db, db_path: Path) -> list[str]:
    """Apply the migrations not yet applied; returns their ids."""
    existing = await _tables(db) - {"schema_migrations"}
    await db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (id TEXT PRIMARY KEY, applied_at REAL NOT NULL)")
    await db.commit()
    cursor = await db.execute("SELECT id FROM schema_migrations")
    done = {row[0] for row in await cursor.fetchall()}
    pending = [name for name in available() if name not in done]
    if not pending:
        return []
    if existing:
        await _backup(db, db_path)
    for name in pending:
        await import_module(f"{__name__}.{name}").up(db)
        await db.execute("INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)", (name, time.time()))
        await db.commit()
        logger.info("Migration %s applied", name)
    return pending
