"""Two dedicated windows (Intermarché and E.Leclerc, P8): each one reuses only its own Chrome.

The port file of a window closed since may give the port of the other
retailer's window (``free_port()`` handed it out again): that window is never
reused, its profile and its tab stay its own.
"""

import asyncio

import pytest

from backend import config
from backend.browser import BrowserManager
from backend.real_chrome import PORT_FILE, parse_port_record
from tests.conftest import browser_missing
from tests.p3_chrome import chrome_path, display, sandbox_args


def test_port_record():
    assert parse_port_record("9333\n/devtools/browser/0b5c-11\n") == (9333, "/devtools/browser/0b5c-11")
    assert parse_port_record("9333\n") == (9333, None)  # written by an older PrixMalin
    assert parse_port_record("9333\n/json/version\n") == (9333, None)
    assert parse_port_record("") == (None, None) and parse_port_record("x\n/devtools/browser/1") == (None, None)


@pytest.fixture
def windows(tmp_path, monkeypatch):
    path = chrome_path()
    if path is None:
        browser_missing("Chromium introuvable pour les fenêtres dédiées")
    monkeypatch.setattr(config, "CHROME_PATH", path)
    monkeypatch.setattr(config, "CHROME_EXTRA_ARGS", sandbox_args())
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche", "leclerc"))
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(config, "REQUEST_INTERVAL_SECONDS", {})
    with display() as available:
        if not available:
            browser_missing("pas d'écran pour les fenêtres dédiées (installez Xvfb)")
        managers = []

        def manager():
            managers.append(BrowserManager(tmp_path / "profile", real_chrome_dir=tmp_path))
            return managers[-1]

        try:
            yield manager
        finally:
            for one in reversed(managers):  # the last one first: it may use a window of the first
                asyncio.run(one.shutdown())


async def mark(page):
    await page.evaluate("() => { window.name = 'tab-of-intermarche' }")
    return page.url


async def name(page):
    return await page.evaluate("() => window.name")


def stale_record(tmp_path, text):
    """Port file left in the E.Leclerc profile by a window closed since."""
    (tmp_path / "chrome-leclerc").mkdir(exist_ok=True)
    (tmp_path / "chrome-leclerc" / PORT_FILE).write_text(text, encoding="utf-8")


def test_window_of_the_other_retailer_is_never_reused(windows, tmp_path):
    """Port file of an older PrixMalin (the port alone): the window of Intermarché is in use here."""
    manager = windows()
    asyncio.run(manager.run("intermarche", mark, timeout=60))
    port, path = parse_port_record((tmp_path / "chrome-intermarche" / PORT_FILE).read_text())
    assert port and path  # the address of that very browser is saved with its port
    stale_record(tmp_path, f"{port}\n")
    assert asyncio.run(manager.run("leclerc", name, timeout=60)) != "tab-of-intermarche"
    leclerc = manager._real["leclerc"]
    assert leclerc._proc is not None and leclerc.endpoint != manager._real["intermarche"].endpoint
    assert parse_port_record((tmp_path / "chrome-leclerc" / PORT_FILE).read_text())[0] != port


def test_only_the_saved_browser_is_reused_after_a_restart(windows, tmp_path):
    """PrixMalin restarted: the port saved for E.Leclerc now answers with Intermarché's Chrome."""
    first = windows()
    asyncio.run(first.run("intermarche", mark, timeout=60))
    port, _ = parse_port_record((tmp_path / "chrome-intermarche" / PORT_FILE).read_text())
    stale_record(tmp_path, f"{port}\n/devtools/browser/0d4a5b7c-closed-since\n")
    again = windows()  # its Intermarché window is not connected yet
    assert asyncio.run(again.run("leclerc", name, timeout=60)) != "tab-of-intermarche"
    assert again._real["leclerc"]._proc is not None  # its own Chrome, started for it
