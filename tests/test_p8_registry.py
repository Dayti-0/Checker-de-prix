"""E.Leclerc Drive in the registry, the configuration and the search engine (P8)."""

import asyncio

import pytest

from backend import config, real_chrome
from backend.browser import BrowserManager
from backend.models import Settings, StoreSelection
from backend.scrapers import SCRAPERS
from backend.services import search, warmup
from tests import fixtures
from tests.conftest import run


def test_sixth_retailer():
    assert list(SCRAPERS)[-1] == "leclerc"
    scraper = SCRAPERS["leclerc"]
    assert (scraper.label, scraper.needs_store, scraper.primary_source) == ("E.Leclerc", True, "api")
    assert scraper.home_url == "https://www.leclercdrive.fr/"
    assert "drive" in scraper.store_hint and "code postal" in scraper.store_hint


def test_configuration_of_the_dedicated_window(monkeypatch):
    monkeypatch.delenv("PRIXMALIN_TIMEOUT", raising=False)
    monkeypatch.delenv("PRIXMALIN_TIMEOUT_LECLERC", raising=False)
    assert config.scraper_timeout("leclerc") == 60
    assert "leclerc" in config.REAL_CHROME_STORES and "intermarche" in config.REAL_CHROME_STORES
    assert config.REQUEST_INTERVAL_SECONDS["leclerc"] == 1.5
    assert config.real_chrome_profile_dir("leclerc").name == "chrome-leclerc"


def test_messages_of_the_window_name_the_retailer():
    assert real_chrome.chrome_missing("E.Leclerc").startswith("E.Leclerc nécessite Google Chrome")
    assert real_chrome.start_failed("E.Leclerc") == (
        "La fenêtre Chrome d'E.Leclerc n'a pas pu démarrer. Fermez-la si elle est ouverte, puis réessayez."
    )
    assert real_chrome.already_open("E.Leclerc").startswith("Une fenêtre Chrome d'E.Leclerc est déjà ouverte")
    assert "pour E.Leclerc (patchright)" in real_chrome.patchright_missing("E.Leclerc")
    assert real_chrome.start_failed("Courses U").startswith("La fenêtre Chrome de Courses U")
    # The messages of Intermarché are unchanged
    assert real_chrome.CHROME_MISSING.startswith("Intermarché nécessite Google Chrome")
    assert real_chrome.START_FAILED.startswith("La fenêtre Chrome d'Intermarché")


def test_no_chrome_installed_names_e_leclerc(tmp_path, monkeypatch):
    from backend.browser import BrowserUnavailable

    monkeypatch.setattr(config, "CHROME_PATH", str(tmp_path / "absent" / "chrome.exe"))
    manager = BrowserManager(tmp_path / "profile", real_chrome_dir=tmp_path)

    async def never(page):
        raise AssertionError("no page without Chrome")

    with pytest.raises(BrowserUnavailable) as error:
        asyncio.run(manager.run("leclerc", never, timeout=20))
    assert str(error.value) == real_chrome.chrome_missing("E.Leclerc")
    windows = {w.store: w for w in manager.status().windows}
    assert windows["leclerc"].error == real_chrome.chrome_missing("E.Leclerc")
    assert windows["leclerc"].label == "E.Leclerc"
    assert manager._real["leclerc"].profile_dir == tmp_path / "chrome-leclerc"
    assert manager._real["leclerc"].domain == "leclercdrive.fr"
    asyncio.run(manager.shutdown())


def test_never_warmed_up():
    settings = Settings(stores={"leclerc": StoreSelection(id="173301", url=fixtures.LECLERC_BASE)})
    assert "leclerc" not in warmup.WARMED_UP
    # Even if it were listed: a dedicated window is never opened at startup
    targets = warmup.warmup_targets(settings, {}, 0, keys=("leclerc", "lidl"), dedicated=("leclerc",))
    assert targets == ["lidl"]


def test_one_try_only_and_no_background_refresh(monkeypatch):
    """A dedicated window is never asked twice for one search, nor in the background."""
    calls = []

    async def failing_run(key, fn, *args, timeout=None, priority="interactive"):
        calls.append(key)
        raise RuntimeError("Page.goto: net::ERR_CONNECTION_RESET at https://fd12-courses.leclercdrive.fr/")

    async def reset_tab(key):
        return None

    monkeypatch.setattr(search.browser, "run", failing_run)
    monkeypatch.setattr(search.browser, "reset_tab", reset_tab)
    monkeypatch.setattr(search, "RETRY_PAUSE_SECONDS", 0)

    async def store_settings():
        from backend.services import settings as settings_service

        await settings_service.set_store("leclerc", StoreSelection(id="173301", url=fixtures.LECLERC_BASE))

    run(store_settings())
    result = run(search.search_store("leclerc", "farine"))
    assert result.status == "error" and calls == ["leclerc"]
    calls.clear()
    run(search.search_store("aldi", "farine"))
    assert calls == ["aldi", "aldi"]
