"""B06: named migrations, WAL journal, copy of the database before migrating."""

import json
import sqlite3
import sys
import types

from backend import config, database, migrations
from backend.services import basket, settings
from tests.conftest import run

OLD_SCHEMA = """
CREATE TABLE search_cache (cache_key TEXT PRIMARY KEY, results_json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE shopping_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    picks_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE app_config (key TEXT);
"""


def rows(path, sql):
    with sqlite3.connect(path) as db:
        result = db.execute(sql).fetchall()
    db.close()
    return result


def test_new_database():
    async def scenario():
        db = await database.get_db()
        mode = await (await db.execute("PRAGMA journal_mode")).fetchone()
        timeout = await (await db.execute("PRAGMA busy_timeout")).fetchone()
        return mode[0], timeout[0]

    assert run(scenario()) == ("wal", 5000)
    tables = {r[0] for r in rows(config.DB_PATH, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"schema_migrations", "search_cache", "settings", "shopping_list"} <= tables
    assert [r[0] for r in rows(config.DB_PATH, "SELECT id FROM schema_migrations")] == migrations.available()
    # Nothing to save before the first migration of an empty database
    assert not migrations.backup_path(config.DB_PATH).exists()


def test_database_of_version_2_0_keeps_its_data():
    with sqlite3.connect(config.DB_PATH) as db:
        db.executescript(OLD_SCHEMA)
        db.execute("INSERT INTO settings VALUES ('settings', ?)", (json.dumps({"show_browser": True}),))
        db.execute(
            "INSERT INTO shopping_list (query, quantity, picks_json, created_at) VALUES ('farine', 2, '{}', 1.0)"
        )
        db.execute("INSERT INTO search_cache VALUES ('aldi||farine', '[]', 1.0)")
    db.close()

    async def scenario():
        return await settings.load_settings(), await basket.get_list()

    current, items = run(scenario())
    assert current.show_browser is True
    assert [(i.query, i.quantity) for i in items] == [("farine", 2)]
    assert rows(config.DB_PATH, "SELECT cache_key FROM search_cache") == [("aldi||farine",)]
    assert rows(config.DB_PATH, "SELECT name FROM sqlite_master WHERE name = 'app_config'") == []
    # The copy taken before migrating is the database as it was
    backup = migrations.backup_path(config.DB_PATH)
    assert backup.name == "test.db.bak"
    assert rows(backup, "SELECT name FROM sqlite_master WHERE name = 'app_config'") == [("app_config",)]
    assert rows(backup, "SELECT query FROM shopping_list") == [("farine",)]


def test_applied_migrations_are_not_replayed(monkeypatch):
    calls = []

    async def up(db):
        calls.append("p9_001_test")
        await db.execute("CREATE TABLE extra (x INTEGER)")

    module = types.ModuleType("backend.migrations.p9_001_test")
    module.up = up
    monkeypatch.setitem(sys.modules, module.__name__, module)

    run(database.get_db())  # p0 only
    first = rows(config.DB_PATH, "SELECT id, applied_at FROM schema_migrations")
    assert [r[0] for r in first] == ["p0_001_initial"]
    run(database.get_db())  # nothing new
    assert rows(config.DB_PATH, "SELECT id, applied_at FROM schema_migrations") == first

    monkeypatch.setattr(migrations, "available", lambda: ["p0_001_initial", "p9_001_test"])
    run(database.get_db())
    run(database.get_db())
    assert calls == ["p9_001_test"]
    assert [r[0] for r in rows(config.DB_PATH, "SELECT id FROM schema_migrations ORDER BY id")] == [
        "p0_001_initial",
        "p9_001_test",
    ]
    # Copy taken before the new migration: without its table
    backup = migrations.backup_path(config.DB_PATH)
    assert rows(backup, "SELECT name FROM sqlite_master WHERE name = 'extra'") == []
    assert rows(config.DB_PATH, "SELECT name FROM sqlite_master WHERE name = 'extra'") == [("extra",)]


def test_migration_names_and_order():
    assert migrations.available()[0] == "p0_001_initial"
    assert migrations.available() == sorted(migrations.available())
