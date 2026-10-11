import asyncio
import os
import re
import shutil
from pathlib import Path

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


ARTIFACTS = os.environ.get("PRIXMALIN_TEST_ARTIFACTS", "")


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path, monkeypatch, request):
    """Each test gets its own database and data directory."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "DEBUG_DIR", tmp_path / "debug")
    request.node.prixmalin_debug_dir = tmp_path / "debug"
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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """In the CI, the pages saved by the scrapers of a failed test go with the artifacts."""
    outcome = yield
    report = outcome.get_result()
    debug_dir = getattr(item, "prixmalin_debug_dir", None)
    if ARTIFACTS and report.failed and debug_dir is not None and debug_dir.is_dir():
        target = Path(ARTIFACTS) / "debug" / re.sub(r"[^\w.-]+", "_", item.nodeid)
        shutil.copytree(debug_dir, target, dirs_exist_ok=True)
