"""A write that fails (database busy) leaves the shared connection usable."""

import asyncio
import sqlite3

import pytest

from backend import config, database
from backend.repos import settings_store


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prixmalin.db")
    run(database.close_db())
    yield config.DB_PATH
    run(database.close_db())


def test_a_failed_write_leaves_no_transaction_open(db_path):
    async def scenario():
        db = await database.get_db()
        await settings_store.set_setting("a", "1")
        await db.execute("PRAGMA busy_timeout = 100")
        other = sqlite3.connect(db_path, isolation_level=None, timeout=5)
        try:
            other.execute("BEGIN IMMEDIATE")  # a backup, an antivirus, another program
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                await settings_store.set_setting("b", "2")
            assert not db.in_transaction
            other.execute("COMMIT")
            assert await settings_store.get_setting("a") == "1"
            # The other program writes again: the app sees it and writes too
            other.execute("INSERT INTO settings (key, value) VALUES ('c', '3')")
            await settings_store.set_setting("b", "2")
        finally:
            other.close()
        assert await settings_store.get_setting("b") == "2"
        assert await settings_store.get_setting("c") == "3"

    run(scenario())


def test_transaction_writes_all_or_nothing(db_path):
    async def scenario():
        await database.get_db()
        with pytest.raises(RuntimeError):
            async with database.transaction() as db:
                await db.execute("INSERT INTO settings (key, value) VALUES ('x', '1')")
                raise RuntimeError("stop")
        assert await settings_store.get_setting("x") is None
        async with database.transaction() as db:
            await db.execute("INSERT INTO settings (key, value) VALUES ('x', '1')")
            await db.execute("INSERT INTO settings (key, value) VALUES ('y', '2')")
        assert (await settings_store.get_setting("x"), await settings_store.get_setting("y")) == ("1", "2")
        assert not (await database.get_db()).in_transaction

    run(scenario())


def test_a_write_of_another_task_does_not_end_an_open_transaction(db_path):
    """A search writes the cache while a list operation is half written (repos call commit())."""

    async def scenario():
        await database.get_db()
        halfway, written = asyncio.Event(), []

        async def search_writes_its_cache():
            await halfway.wait()
            await settings_store.set_setting("cache", "fresh")  # execute() then commit()
            written.append(True)

        other = asyncio.create_task(search_writes_its_cache())
        with pytest.raises(RuntimeError):
            async with database.transaction() as db:
                await db.execute("INSERT INTO settings (key, value) VALUES ('a', '1')")
                halfway.set()
                await asyncio.sleep(0.05)  # the other task runs now
                await db.execute("INSERT INTO settings (key, value) VALUES ('b', '2')")
                raise RuntimeError("list full")
        await other
        # Nothing of the transaction is kept, the write of the other task is
        assert (await settings_store.get_setting("a"), await settings_store.get_setting("b")) == (None, None)
        assert written and await settings_store.get_setting("cache") == "fresh"

    run(scenario())


def test_a_transaction_inside_a_transaction_joins_it(db_path):
    async def scenario():
        await database.get_db()
        with pytest.raises(RuntimeError):
            async with database.transaction() as db:
                await db.execute("INSERT INTO settings (key, value) VALUES ('a', '1')")
                async with database.transaction() as inner:  # a repo helper opening its own
                    await inner.execute("INSERT INTO settings (key, value) VALUES ('b', '2')")
                    await inner.commit()  # does not end the outer one
                raise RuntimeError("stop")
        assert (await settings_store.get_setting("a"), await settings_store.get_setting("b")) == (None, None)
        assert not (await database.get_db()).in_transaction

    run(scenario())


def test_a_task_started_in_a_transaction_waits_for_the_next_one(db_path):
    """A task created inside a transaction that writes after its end is not part of the next one."""

    async def scenario():
        await database.get_db()
        go = asyncio.Event()

        async def late_write():
            await go.wait()
            await settings_store.set_setting("late", "1")

        async with database.transaction():
            task = asyncio.create_task(late_write())  # copies the context of the transaction
        with pytest.raises(RuntimeError):
            async with database.transaction() as db:
                await db.execute("INSERT INTO settings (key, value) VALUES ('a', '1')")
                go.set()
                await asyncio.sleep(0.05)
                raise RuntimeError("stop")
        await task
        assert await settings_store.get_setting("late") == "1"
        assert await settings_store.get_setting("a") is None

    run(scenario())


def test_a_read_of_another_task_never_sees_a_half_written_transaction(db_path):
    async def scenario():
        db = await database.get_db()
        halfway, seen = asyncio.Event(), []

        async def read_the_list():
            await halfway.wait()
            async with db.execute("SELECT key FROM settings WHERE key IN ('a', 'b')") as cursor:
                seen.append([row["key"] for row in await cursor.fetchall()])

        reader = asyncio.create_task(read_the_list())
        with pytest.raises(RuntimeError):
            async with database.transaction() as tx:
                await tx.execute("INSERT INTO settings (key, value) VALUES ('a', '1')")
                halfway.set()
                await asyncio.sleep(0.05)
                raise RuntimeError("stop")
        await reader
        assert seen == [[]]
        cursor = await db.execute("SELECT COUNT(*) AS n FROM settings")
        assert (await cursor.fetchone())["n"] == 0 and cursor.rowcount == -1

    run(scenario())
