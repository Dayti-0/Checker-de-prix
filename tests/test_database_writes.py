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
