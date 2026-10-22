"""The SQLite database: one shared connection, WAL journal, named migrations.

The shared connection commits each statement by itself (autocommit): a write
that fails (database busy for more than 5 s: a backup, an antivirus, a test)
leaves no transaction open behind it. In the default mode of sqlite3 it did,
and every later write of the app failed until a restart. Several statements
that must be written together go in ``async with transaction() as db:``.

While a transaction is open, the statements of the other tasks wait for its
end (``SharedConnection``): otherwise the ``commit()`` of a cache write in the
middle of it committed half of it, and a write of another task was undone
with it.

The tables are created and changed by the migrations of ``backend/migrations/``.
The queries live in ``backend/repos/`` (one module per area); they are also
reachable from here, e.g. ``database.get_cached(...)``, as before the split.
"""

import asyncio
import contextlib
import contextvars
import importlib
from collections.abc import AsyncIterator

import aiosqlite

from backend import config, migrations

_db: "SharedConnection | None" = None
_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None
_write_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None

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


def _transaction_lock() -> asyncio.Lock:
    global _write_lock
    loop = asyncio.get_running_loop()
    if _write_lock is None or _write_lock[0] is not loop:
        _write_lock = (loop, asyncio.Lock())
    return _write_lock[1]


# The transaction open in this context (copied by the tasks it creates), and the open one
_owner: contextvars.ContextVar[object | None] = contextvars.ContextVar("prixmalin_transaction", default=None)
_open_transaction: object | None = None


def _in_open_transaction() -> bool:
    owner = _owner.get()
    return owner is not None and owner is _open_transaction


async def _serialized(method, *args, **kwargs):
    """``method(...)``, after the transaction of another task if one is open."""
    if _in_open_transaction():
        return await method(*args, **kwargs)
    async with _transaction_lock():
        return await method(*args, **kwargs)


class _Cursor:
    """A cursor whose reads also wait for the transaction of another task (no half-written rows)."""

    def __init__(self, cursor: aiosqlite.Cursor):
        self._cursor = cursor

    def __getattr__(self, name: str):
        return getattr(self._cursor, name)

    async def fetchone(self):
        return await _serialized(self._cursor.fetchone)

    async def fetchmany(self, *args, **kwargs):
        return await _serialized(self._cursor.fetchmany, *args, **kwargs)

    async def fetchall(self):
        return await _serialized(self._cursor.fetchall)

    async def __aiter__(self):
        for row in await self.fetchall():
            yield row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        await self._cursor.close()


class _Statement:
    """A statement of the shared connection, awaited or used with ``async with`` like aiosqlite's."""

    def __init__(self, method, args, kwargs):
        self._method, self._args, self._kwargs = method, args, kwargs
        self._result = None

    async def _run(self):
        result = await _serialized(self._method, *self._args, **self._kwargs)
        return _Cursor(result) if isinstance(result, aiosqlite.Cursor) else result

    def __await__(self):
        return self._run().__await__()

    async def __aenter__(self):
        self._result = await self._run()
        return self._result

    async def __aexit__(self, *exc) -> None:
        close = getattr(self._result, "close", None)
        if close is not None:
            await close()


class SharedConnection:
    """The aiosqlite connection of the app: outside a transaction, a statement waits for the open one.

    Inside a transaction, ``commit()`` does nothing (the transaction commits at
    its end) and ``rollback()`` is refused (raise an exception instead).
    """

    def __init__(self, connection: aiosqlite.Connection):
        object.__setattr__(self, "_connection", connection)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._connection, name, value)

    def execute(self, *args, **kwargs) -> _Statement:
        return _Statement(self._connection.execute, args, kwargs)

    def executemany(self, *args, **kwargs) -> _Statement:
        return _Statement(self._connection.executemany, args, kwargs)

    def executescript(self, *args, **kwargs) -> _Statement:
        return _Statement(self._connection.executescript, args, kwargs)

    def execute_insert(self, *args, **kwargs) -> _Statement:
        return _Statement(self._connection.execute_insert, args, kwargs)

    def execute_fetchall(self, *args, **kwargs) -> _Statement:
        return _Statement(self._connection.execute_fetchall, args, kwargs)

    async def commit(self) -> None:
        if not _in_open_transaction():
            await _serialized(self._connection.commit)

    async def rollback(self) -> None:
        if _in_open_transaction():
            raise RuntimeError("raise an exception to undo a transaction")
        await _serialized(self._connection.rollback)


async def get_db() -> SharedConnection:
    global _db
    if _db is not None:
        return _db
    async with _open_lock():
        if _db is None:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            # Autocommit: no transaction ever left open by a failed write
            db = await aiosqlite.connect(config.DB_PATH, isolation_level=None)
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
            _db = SharedConnection(db)
    return _db


@contextlib.asynccontextmanager
async def transaction() -> AsyncIterator[SharedConnection]:
    """Several statements written together, or not at all.

    One transaction at a time: the statements of the other tasks wait for its
    end. A transaction opened inside it (a helper of a repo) is part of it.
    """
    global _open_transaction
    db = await get_db()
    if _in_open_transaction():
        yield db
        return
    raw = db._connection
    async with _transaction_lock():
        marker = object()
        token = _owner.set(marker)
        _open_transaction = marker
        try:
            await raw.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                await raw.rollback()
                raise
            await raw.commit()
        finally:
            _open_transaction = None
            _owner.reset(token)


async def close_db() -> None:
    global _db
    if _db is not None:
        db, _db = _db, None
        await db._connection.close()
