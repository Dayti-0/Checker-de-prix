"""B86: check of the updates (once a day), release zip and notes, mettre-a-jour.bat."""

import importlib.util
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import __version__, main
from backend.api import updates
from backend.services import prefs
from tests.conftest import run

ROOT = Path(__file__).resolve().parent.parent


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ".github" / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def github(monkeypatch):
    """Fake GitHub API: ``github["answer"] = (status, json)``; ``github["calls"]`` counts the requests."""
    state = {"answer": (200, {"tag_name": "v9.0.0", "html_url": "https://github.com/x/y/releases/v9.0.0"}), "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        assert request.url.path == "/repos/Dayti-0/Checker-de-prix/releases/latest"
        assert request.headers["user-agent"].startswith("PrixMalin/")
        status, body = state["answer"]
        if status == 0:
            raise httpx.ConnectError("no network")
        return httpx.Response(status, json=body)

    monkeypatch.setattr(updates, "HTTP_TRANSPORT", httpx.MockTransport(handler))
    return state


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


# --- versions (pure) ---------------------------------------------------------------


def test_parse_and_compare_versions():
    assert updates.parse_version("v3.0.0") == (3, 0, 0)
    assert updates.parse_version("3.1") == (3, 1, 0)
    assert updates.parse_version(" 10.2.3 ") == (10, 2, 3)
    for bad in ("3.0.0-rc1", "", None, "vtrois", "3"):
        assert updates.parse_version(bad) is None, bad
    assert updates.is_newer("3.0.0", "2.1.0")
    assert updates.is_newer("2.10.0", "2.9.9")  # numbers, not text
    assert not updates.is_newer("2.1.0", "2.1.0")
    assert not updates.is_newer("2.0.9", "2.1.0")
    assert not updates.is_newer(None, "2.1.0") and not updates.is_newer("x", "2.1.0")


def test_one_check_a_day():
    day = updates.CHECK_INTERVAL_SECONDS
    assert updates.check_due(updates.UpdatePrefs(), 1000.0)
    assert not updates.check_due(updates.UpdatePrefs(checked_at=1000.0), 1000.0 + day - 1)
    assert updates.check_due(updates.UpdatePrefs(checked_at=1000.0), 1000.0 + day)
    assert updates.check_due(updates.UpdatePrefs(checked_at=1000.0 + 3 * day), 1000.0)  # clock moved back
    assert not updates.check_due(updates.UpdatePrefs(enabled=False), 1000.0)


def test_release_of():
    assert updates.release_of({"tag_name": "v3.1.0", "html_url": "https://github.com/a/b/releases/v3.1.0"}) == (
        "3.1.0",
        "https://github.com/a/b/releases/v3.1.0",
    )
    assert updates.release_of({"tag_name": "v3.1.0", "html_url": "javascript:alert(1)"}) == ("3.1.0", None)
    assert updates.release_of({"tag_name": "v4.0.0", "prerelease": True}) is None
    assert updates.release_of({"tag_name": "v4.0.0", "draft": True}) is None
    assert updates.release_of({"tag_name": "nightly"}) is None
    assert updates.release_of([]) is None


# --- check and routes ------------------------------------------------------------


def test_check_finds_a_new_version(client, github):
    before = client.get("/api/updates").json()
    assert before["current"] == __version__ and before["checked_at"] is None and github["calls"] == 0
    state = client.post("/api/updates/check").json()
    assert state["available"] is True and state["latest"] == "9.0.0"
    assert state["url"] == "https://github.com/x/y/releases/v9.0.0" and state["error"] is None
    assert github["calls"] == 1
    assert client.get("/api/updates").json() == state  # read from the preferences, no request
    assert github["calls"] == 1


def test_no_release_yet_and_no_network(client, github):
    github["answer"] = (404, {"message": "Not Found"})
    state = client.post("/api/updates/check").json()
    assert state["available"] is False and state["latest"] is None and state["checked_at"]
    github["answer"] = (200, {"tag_name": f"v{__version__}"})
    assert client.post("/api/updates/check").json()["latest"] == __version__
    github["answer"] = (0, None)
    state = client.post("/api/updates/check").json()
    assert state["error"] and "Internet" in state["error"]
    assert state["latest"] == __version__  # the last known answer is kept
    github["answer"] = (500, {})
    assert client.post("/api/updates/check").json()["error"]


def test_auto_check_runs_once_a_day(github, monkeypatch):
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise RuntimeError("stop")

    monkeypatch.setattr(updates.asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError):
        run(updates.auto_check())
    assert github["calls"] == 1 and len(sleeps) == 3  # the 2nd and 3rd turns: checked less than a day ago


def test_auto_check_can_be_disabled(client, github, monkeypatch):
    assert client.patch("/api/updates", json={"enabled": False}).json()["enabled"] is False

    async def sleep(seconds):
        raise RuntimeError("stop")

    monkeypatch.setattr(updates.asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError):
        run(updates.auto_check())
    assert github["calls"] == 0
    saved = run(prefs.get(updates.UPDATES_SECTION, updates.UpdatePrefs))
    assert saved.enabled is False


def test_updates_need_the_code_on_the_phone():
    with TestClient(main.app, client=("192.168.1.20", 5000), base_url="http://192.168.1.10:8000") as phone:
        assert phone.get("/api/updates").status_code == 401


# --- release zip and notes -------------------------------------------------------


def test_release_zip(tmp_path):
    build = load_script("build_release")
    target = build.build("9.9.9", tmp_path)
    assert target.name == "PrixMalin-9.9.9.zip"
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert all(n.startswith("PrixMalin-9.9.9/") for n in names)
        short = {n.split("/", 1)[1] for n in names}
        for needed in ("lancer.bat", "mettre-a-jour.bat", "installer-raccourci.bat", "requirements.txt", "README.md"):
            assert needed in short, needed
        assert "backend/main.py" in short and "frontend/index.html" in short
        dev = ("CLAUDE.md", "requirements-dev.txt")
        assert not [n for n in short if n.startswith(("tests/", ".github/")) or n in dev]
        assert not [n for n in short if "__pycache__" in n or n.endswith(".pyc")]
        for name in names:
            if name.endswith(".bat"):
                data = archive.read(name)
                assert data.count(b"\n") == data.count(b"\r\n") > 0, name


def test_release_selection_rules():
    build = load_script("build_release")
    names = ["backend/a.py", "backend/__pycache__/a.cpython-313.pyc", "tests/test_x.py", "lancer.bat", "CLAUDE.md"]
    assert build.selected(names) == ["backend/a.py", "lancer.bat"]
    assert build.crlf(b"a\nb\r\nc\n") == b"a\r\nb\r\nc\r\n"


def test_release_notes():
    notes = load_script("release_notes").notes
    changelog = "# Journal\n\n## [3.1.0] - 2026-11-02\n\n- Nouveau\n- Corrigé\n\n## [3.0.0]\n\n- Ancien\n"
    assert notes(changelog, "3.1.0") == "- Nouveau\n- Corrigé"
    assert notes(changelog, "3.0.0") == "- Ancien"
    assert notes(changelog, "4.0.0") == "PrixMalin 4.0.0. Voir CHANGELOG.md."
    assert "Non publié" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_release_workflow_and_update_script():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in workflow and "build_release.py" in workflow and "release_notes.py" in workflow
    data = (ROOT / "mettre-a-jour.bat").read_bytes()
    assert data.isascii() and data.count(b"\n") == data.count(b"\r\n")
    text = data.decode("ascii")
    assert "git pull --ff-only" in text and 'if exist ".git" goto :git' in text
    assert "api.github.com/repos/Dayti-0/Checker-de-prix/releases/latest" in text
    assert "Invoke-WebRequest" in text and "'venv', 'data', '.git'" in text
    assert "lancer.bat" in text and "%TEMP%\\prixmalin-mise-a-jour.bat" in text
    # No release yet (GitHub answers 404): nothing to update, not « check Internet »
    assert "if ($status -eq 404)" in text and "rien a mettre a jour" in text and "exit 2" in text
    assert text.index("if errorlevel 2 goto :nothing_new") < text.index("if errorlevel 1 goto :zip_failed")


def test_update_state_text_in_french():
    state = updates.state_of(updates.UpdatePrefs(latest="9.0.0", checked_at=1.0, failure="network"))
    assert state.available and state.error == "La dernière vérification n'a pas pu joindre Internet."
    assert json.loads(state.model_dump_json())["current"] == __version__


# --- review: GitHub refusing is not « no Internet » ----------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (httpx.ConnectError("no network"), "La dernière vérification n'a pas pu joindre Internet."),
        (httpx.Response(403, json={"message": "API rate limit exceeded"}), "GitHub"),
        (httpx.Response(503, text="unavailable"), "GitHub"),
    ],
)
def test_update_check_failures(monkeypatch, answer, expected):
    def handler(request):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(updates, "HTTP_TRANSPORT", httpx.MockTransport(handler))
    state = run(updates.check())
    assert expected in state.error
    if expected == "GitHub":
        assert "Internet" not in state.error
