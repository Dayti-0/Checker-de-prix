"""B85: folder of the data outside the app, backup file, daily copies of the database."""

import json
import logging
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import backup, config, main, security
from backend.services import hooks
from tests.conftest import run


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def paths(monkeypatch):
    """config paths restored after a test that calls use_data_dir()."""
    for name in ("DATA_DIR", "DB_PATH", "BROWSER_PROFILE_DIR", "DEBUG_DIR"):
        monkeypatch.setattr(config, name, getattr(config, name))


# --- folder of the data -----------------------------------------------------------


def test_default_folder_of_the_data(tmp_path):
    windows = config.default_data_dir({"LOCALAPPDATA": r"C:\Users\Zoé\AppData\Local"}, "win32")
    assert str(windows).replace("/", "\\").endswith(r"AppData\Local\PrixMalin")
    assert config.default_data_dir({"XDG_DATA_HOME": str(tmp_path)}, "linux") == tmp_path / "prixmalin"
    assert config.default_data_dir({}, "linux") == Path.home() / ".local" / "share" / "prixmalin"
    assert config.initial_data_dir({"PRIXMALIN_DATA_DIR": str(tmp_path / "x")}) == tmp_path / "x"
    legacy = tmp_path / "app" / "data"
    env = {"XDG_DATA_HOME": str(tmp_path / "share")}
    assert config.initial_data_dir(env, legacy) == tmp_path / "share" / "prixmalin"
    legacy.mkdir(parents=True)
    assert config.initial_data_dir(env, legacy) == legacy  # waits to be moved by run()
    (tmp_path / "share" / "prixmalin").mkdir(parents=True)
    assert config.initial_data_dir(env, legacy) == tmp_path / "share" / "prixmalin"


def test_use_data_dir_moves_every_path(paths, tmp_path):
    config.use_data_dir(tmp_path / "ailleurs")
    assert config.DB_PATH == tmp_path / "ailleurs" / "prixmalin.db"
    assert config.BROWSER_PROFILE_DIR == tmp_path / "ailleurs" / "browser-profile"
    assert config.DEBUG_DIR == tmp_path / "ailleurs" / "debug"
    assert config.real_chrome_profile_dir("intermarche") == tmp_path / "ailleurs" / "chrome-intermarche"


def make_legacy(folder: Path) -> None:
    (folder / "browser-profile").mkdir(parents=True)
    (folder / "browser-profile" / "Cookies").write_bytes(b"cookies")
    (folder / "prixmalin.db").write_bytes(b"base")


def test_old_data_folder_is_moved(paths, tmp_path):
    legacy, target = tmp_path / "Mon appli à moi" / "data", tmp_path / "local" / "PrixMalin"
    make_legacy(legacy)
    level, message = backup.migrate_legacy_data(legacy, target, env={})
    assert level == logging.INFO and "moved" in message
    assert not legacy.exists()
    assert (target / "browser-profile" / "Cookies").read_bytes() == b"cookies"
    assert config.DATA_DIR == target and config.DB_PATH == target / "prixmalin.db"
    assert backup.migrate_legacy_data(legacy, target, env={}) is None  # nothing left to move


def test_old_data_folder_moved_to_another_disk(paths, tmp_path, monkeypatch):
    legacy, target = tmp_path / "app" / "data", tmp_path / "local" / "PrixMalin"
    make_legacy(legacy)

    def rename(src, dst, real=backup.os.rename):
        if Path(src) == legacy:
            raise OSError(18, "Invalid cross-device link")
        return real(src, dst)

    monkeypatch.setattr(backup.os, "rename", rename)
    level, _ = backup.migrate_legacy_data(legacy, target, env={})
    assert level == logging.INFO
    assert (target / "prixmalin.db").read_bytes() == b"base" and not legacy.exists()
    assert not (target.parent / "PrixMalin.copie-en-cours").exists()


def test_a_folder_in_use_is_kept(paths, tmp_path, monkeypatch):
    legacy, target = tmp_path / "app" / "data", tmp_path / "local" / "PrixMalin"
    make_legacy(legacy)

    def locked(src, dst):
        raise PermissionError(13, "Le processus ne peut pas accéder au fichier")

    monkeypatch.setattr(backup.os, "rename", locked)
    level, message = backup.migrate_legacy_data(legacy, target, env={})
    assert level == logging.WARNING and "kept" in message
    assert (legacy / "prixmalin.db").exists() and not target.exists()
    assert config.DATA_DIR == legacy
    monkeypatch.undo()
    # Another PrixMalin uses it: not even tried
    level, message = backup.migrate_legacy_data(legacy, target, env={}, in_use=lambda p: True)
    assert "in use" in message and config.DATA_DIR == legacy and legacy.exists()


def test_the_new_folder_wins_when_both_exist(paths, tmp_path):
    legacy, target = tmp_path / "app" / "data", tmp_path / "local" / "PrixMalin"
    make_legacy(legacy)
    target.mkdir(parents=True)
    level, message = backup.migrate_legacy_data(legacy, target, env={})
    assert level == logging.WARNING and "ignored" in message
    assert config.DATA_DIR == target and legacy.exists()
    assert backup.migrate_legacy_data(legacy, target, env={"PRIXMALIN_DATA_DIR": "x"}) is None


# --- backup file ---------------------------------------------------------------


def fill(client):
    client.patch("/api/settings", json={"show_browser": True})
    client.post("/api/list", json={"query": "farine", "quantity": 2})
    client.post("/api/list", json={"query": "riz"})


def test_backup_round_trip(client):
    fill(client)
    answer = client.get("/api/backup")
    assert answer.status_code == 200
    assert answer.headers["content-disposition"].startswith('attachment; filename="prixmalin-sauvegarde-')
    saved = answer.json()
    assert saved["format"] == "prixmalin" and saved["version"] == 1
    assert {"settings", "shopping_list"} <= set(saved["sections"])
    assert "browser-profile" not in json.dumps(saved)
    # Everything changed, then the backup put back
    client.delete("/api/list")
    client.post("/api/list", json={"query": "sel"})
    client.patch("/api/settings", json={"show_browser": False})
    restored = client.post("/api/restore", json={"mode": "replace", "backup": saved})
    assert restored.status_code == 200
    assert set(restored.json()["restored"]) >= {"settings", "shopping_list"}
    again = client.get("/api/backup").json()
    strip = lambda b: {k: v for k, v in b.items() if k != "created_at"}  # noqa: E731
    lines = lambda b: [(i["query"], i["quantity"]) for i in b["sections"]["shopping_list"]]  # noqa: E731
    assert lines(again) == lines(saved)
    assert again["sections"]["settings"] == saved["sections"]["settings"]
    assert strip(again).keys() == strip(saved).keys()
    assert client.get("/api/settings").json()["show_browser"] is True


def test_backup_never_holds_the_access_code(client):
    from backend import security

    code = security.access_secret().code
    text = client.get("/api/backup").text
    assert code not in text and security.access_secret().key not in text


def test_merge_keeps_the_current_data(client):
    fill(client)
    saved = client.get("/api/backup").json()
    client.delete("/api/list")
    client.post("/api/list", json={"query": "Riz", "quantity": 5})
    client.post("/api/list", json={"query": "sel"})
    answer = client.post("/api/restore", json={"mode": "merge", "backup": saved})
    assert answer.status_code == 200 and answer.json()["mode"] == "merge"
    lines = [(i["query"], i["quantity"]) for i in client.get("/api/list").json()]
    assert ("Riz", 5) in lines and ("sel", 1) in lines and ("farine", 2) in lines
    assert [q for q, _ in lines].count("riz") + [q for q, _ in lines].count("Riz") == 1


def test_merge_section_rules():
    assert backup.merge_section({"a": "1", "b": "2"}, {"b": "x", "c": "3"}) == {"a": "1", "b": "2", "c": "3"}
    merged = backup.merge_section([{"id": 1, "query": "Riz"}], [{"id": 9, "query": "riz "}, {"id": 2, "query": "sel"}])
    assert merged == [{"id": 1, "query": "Riz"}, {"id": 2, "query": "sel"}]
    assert backup.merge_section([1, 2], [2, 3]) == [1, 2, 3]
    assert backup.merge_section(None, {"x": 1}) == {"x": 1}
    assert backup.merge_section("garde", "autre") == "garde"


def test_restore_refuses_a_bad_file(client):
    fill(client)
    before = client.get("/api/list").json()
    for body in (b"pas du json", b'{"mode": "replace", "backup": {"format": "autre", "version": 1, "sections": {}}}'):
        answer = client.post("/api/restore", content=body, headers={"content-type": "application/json"})
        assert answer.status_code == 422 and answer.json()["code"] == "backup_invalid"
    broken = {"format": "prixmalin", "version": 1, "sections": {"shopping_list": [{"query": None}]}}
    answer = client.post("/api/restore", json={"mode": "replace", "backup": broken})
    assert answer.status_code == 422 and "rien n'a été changé" in answer.json()["detail"]
    assert client.get("/api/list").json() == before  # all or nothing
    newer = {"format": "prixmalin", "version": 99, "sections": {}}
    answer = client.post("/api/restore", json={"mode": "replace", "backup": newer})
    assert answer.status_code == 422 and answer.json()["code"] == "backup_too_new"


def test_restore_ignores_unknown_parts(client):
    saved = client.get("/api/backup").json()
    saved["sections"]["suivis_futurs"] = [{"x": 1}]
    answer = client.post("/api/restore", json={"mode": "replace", "backup": saved})
    assert answer.status_code == 200 and answer.json()["ignored"] == ["suivis_futurs"]


def test_restore_is_limited_to_10_mo(client, monkeypatch):
    monkeypatch.setattr(backup, "MAX_RESTORE_BYTES", 1000)
    body = json.dumps(
        {"mode": "replace", "backup": {"format": "prixmalin", "version": 1, "sections": {"x": "a" * 2000}}}
    )
    answer = client.post("/api/restore", content=body, headers={"content-type": "application/json"})
    assert answer.status_code == 413 and "10 Mo" in answer.json()["detail"]
    assert backup.MAX_RESTORE_BYTES == 1000 and backup.KEEP_COPIES == 7


def test_a_provider_registered_later_is_backed_up(client, monkeypatch):
    store = {"value": ["un"]}

    async def export():
        return store["value"]

    async def restore(data):
        store["value"] = data

    monkeypatch.setattr(hooks, "_backups", dict(hooks._backups))
    hooks.register_backup("modeles", export, restore)
    saved = client.get("/api/backup").json()
    assert saved["sections"]["modeles"] == ["un"]
    store["value"] = []
    client.post("/api/restore", json={"mode": "replace", "backup": saved})
    assert store["value"] == ["un"]


# --- daily copies --------------------------------------------------------------


def test_copies_to_delete_keeps_the_last_seven():
    names = [f"prixmalin-2026-10-{d:02d}.db" for d in range(1, 11)] + ["notes.txt", "prixmalin-x.db"]
    assert backup.copies_to_delete(names) == [
        "prixmalin-2026-10-01.db",
        "prixmalin-2026-10-02.db",
        "prixmalin-2026-10-03.db",
    ]
    assert backup.copies_to_delete(names[:3]) == []


def test_daily_copy_and_rotation(client):
    fill(client)  # the database exists
    folder = backup.copies_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for day in range(1, 9):
        (folder / f"prixmalin-2026-09-{day:02d}.db").write_bytes(b"ancienne")
    (folder / "a-garder.txt").write_text("x")
    made = run(backup.daily_copy(date(2026, 10, 22)))
    assert made == folder / "prixmalin-2026-10-22.db"
    with sqlite3.connect(made) as db:
        assert db.execute("SELECT COUNT(*) FROM shopping_list").fetchone()[0] == 2
    db.close()
    names = sorted(f.name for f in folder.iterdir())
    assert len([n for n in names if n.endswith(".db")]) == 7 and "a-garder.txt" in names
    assert "prixmalin-2026-09-01.db" not in names and "prixmalin-2026-09-02.db" not in names
    assert run(backup.daily_copy(date(2026, 10, 22))) is None  # once a day
    info = client.get("/api/backup/info").json()
    assert info["count"] == 7 and info["keep"] == 7 and info["last_at"] is not None
    assert info["data_dir"] is not None  # TestClient: the PC


def test_no_copy_without_a_database(tmp_path):
    assert run(backup.daily_copy(date(2026, 10, 22))) is None
    assert not backup.copies_dir().exists()


# --- review: deep files, parts checked, settings of the PC kept ----------------------

PC_ADDRESS = "http://192.168.1.10:8000"


def test_deeply_nested_backup_is_refused_cleanly(client):
    body = b"[" * 200000 + b"]" * 200000
    answer = client.post("/api/restore", content=body, headers={"content-type": "application/json"})
    assert answer.status_code == 422 and answer.json()["code"] == "backup_invalid"


def backup_with(settings: dict) -> dict:
    return {"format": "prixmalin", "version": 1, "sections": {"settings": settings}}


@pytest.mark.parametrize(
    "settings",
    [
        {"settings": {"x": 1}},  # not text
        {"settings": "pas du json"},  # the settings of P4: not a Settings
        {"settings": json.dumps({"show_browser": "peut-être"})},
        {"pref:p4.coursesu": "pas du json"},  # preferences: a JSON object
        {"pref:p4.coursesu": "[1, 2]"},
        ["une", "liste"],
        {"pref:p4.coursesu": "[" * 100000 + "]" * 100000},  # too deep for json.loads
    ],
)
def test_settings_section_is_validated(client, settings):
    client.patch("/api/settings", json={"show_browser": True})
    before = client.get("/api/backup").json()["sections"]["settings"]
    answer = client.post("/api/restore", json={"mode": "replace", "backup": backup_with(settings)})
    assert answer.status_code == 422 and answer.json()["code"] == "backup_invalid"
    assert client.get("/api/backup").json()["sections"]["settings"] == before
    assert client.get("/api/settings").json()["show_browser"] is True


def test_settings_of_the_pc_stay_out_of_the_backup(client):
    client.patch("/api/security", json={"allow_lan": False})
    client.patch("/api/updates", json={"enabled": False})
    saved = client.get("/api/backup").json()["sections"]["settings"]
    assert "pref:p7.security" not in saved and "pref:p7.updates" not in saved


@pytest.mark.parametrize("mode", ["replace", "merge"])
def test_restore_never_changes_the_settings_of_the_pc(client, mode):
    # A phone restores a file that disables its access and announces a fake version
    forged = backup_with(
        {
            "pref:p7.security": json.dumps({"allow_lan": False}),
            "pref:p7.updates": json.dumps({"latest": "99.0.0", "url": "https://evil.example/", "checked_at": 1}),
        }
    )
    cookie = f"{security.ACCESS_COOKIE}={security.access_token(security.access_secret())}"
    headers = {"Cookie": cookie, "X-PrixMalin": "1"}
    with TestClient(main.app, client=("192.168.1.20", 5000), base_url=PC_ADDRESS, headers=headers) as phone:
        assert phone.post("/api/restore", json={"mode": mode, "backup": forged}).status_code == 200
        assert phone.get("/api/settings").status_code == 200  # still allowed
    assert client.get("/api/security").json()["allow_lan"] is True
    assert client.get("/api/updates").json()["latest"] is None
    # The PC keeps its own values after a « replace » too
    client.patch("/api/security", json={"allow_lan": False})
    client.post("/api/restore", json={"mode": "replace", "backup": backup_with({})})
    assert client.get("/api/security").json()["allow_lan"] is False
