import asyncio
import os

import pytest

os.environ.setdefault("PRIXMALIN_WARMUP", "0")

from backend import config, database  # noqa: E402

# In the CI the browser tests must run: a missing Chromium is a failure, not a skip
REQUIRE_BROWSER = os.environ.get("PRIXMALIN_REQUIRE_BROWSER", "") not in ("", "0")


def browser_missing(reason: str):
    """Skip a test that needs Chromium, or fail it when PRIXMALIN_REQUIRE_BROWSER=1."""
    if REQUIRE_BROWSER:
        pytest.fail(f"{reason} (PRIXMALIN_REQUIRE_BROWSER=1)", pytrace=False)
    pytest.skip(reason)


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
