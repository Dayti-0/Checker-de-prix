import asyncio
import os

import pytest

os.environ.setdefault("PRIXMALIN_WARMUP", "0")

from backend import config, database  # noqa: E402


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path, monkeypatch):
    """Each test gets its own database and data directory."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "DEBUG_DIR", tmp_path / "debug")
    database._db = None
    yield tmp_path
    database._db = None


def run(coro):
    """Run a coroutine, closing the database connection in the same loop."""

    async def wrapper():
        try:
            return await coro
        finally:
            await database.close_db()

    return asyncio.run(wrapper())
