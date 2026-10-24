"""B45: time limits, one more try only after a navigation error, French messages only."""

import json

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from backend import config
from backend.browser import QueueTimeout, browser
from backend.models import Product
from backend.scrapers.base import BlockedError
from backend.scrapers.common import is_navigation_error, is_timeout_error
from backend.services import search
from tests.conftest import run


class FakeBrowser:
    """``browser.run`` answering the given results in turn (exceptions are raised)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []
        self.resets: list[str] = []

    async def run(self, key, fn, *args, timeout=None, priority="interactive"):
        self.calls.append({"key": key, "timeout": timeout, "priority": priority})
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def reset_tab(self, key):
        self.resets.append(key)


@pytest.fixture
def fake(monkeypatch):
    def install(*answers):
        fake_browser = FakeBrowser(*answers)
        monkeypatch.setattr(browser, "run", fake_browser.run)
        monkeypatch.setattr(browser, "reset_tab", fake_browser.reset_tab)
        monkeypatch.setattr(search, "RETRY_PAUSE_SECONDS", 0)
        return fake_browser

    return install


def test_playwright_timeout_gives_the_timeout_status_after_one_try(fake):
    browser_ = fake(PlaywrightTimeout("Timeout 30000ms exceeded."))
    result = run(search.search_store("aldi", "farine"))
    assert result.status == "timeout"
    assert result.message == "Le site Aldi met trop de temps à répondre."
    assert len(browser_.calls) == 1


def test_queue_timeout_has_its_own_message(fake):
    fake(QueueTimeout())
    result = run(search.search_store("aldi", "farine"))
    assert result.status == "timeout" and "en attente" in result.message


def test_invalid_json_is_an_error_without_retry(fake):
    try:
        json.loads("<html>")
    except ValueError as e:
        error = e
    browser_ = fake(error)
    result = run(search.search_store("lidl", "farine"))
    assert result.status == "error"
    assert result.message == "La recherche sur Lidl a échoué. Réessayez dans un instant."
    assert "Expecting" not in result.message
    assert len(browser_.calls) == 1


def test_navigation_error_is_tried_again_in_a_fresh_tab(fake):
    browser_ = fake(
        PlaywrightError("Page.goto: Navigation failed because page crashed!"),
        [Product(store="lidl", name="Farine", price=0.75)],
    )
    result = run(search.search_store("lidl", "farine"))
    assert result.status == "ok" and [p.name for p in result.products] == ["Farine"]
    assert len(browser_.calls) == 2
    assert browser_.resets == ["lidl"]  # the tab was replaced before the new try


def test_closed_tab_is_tried_again(fake):
    browser_ = fake(PlaywrightError("Target page, context or browser has been closed"), [])
    assert run(search.search_store("aldi", "farine")).status == "empty"
    assert len(browser_.calls) == 2


def test_second_navigation_error_is_reported(fake):
    browser_ = fake(
        PlaywrightError("net::ERR_NAME_NOT_RESOLVED at https://www.lidl.fr/"),
        PlaywrightError("net::ERR_NAME_NOT_RESOLVED at https://www.lidl.fr/"),
    )
    result = run(search.search_store("lidl", "farine"))
    assert result.status == "error"
    assert result.message == "Lidl est injoignable. Vérifiez votre connexion Internet."
    assert len(browser_.calls) == 2


def test_intermarche_is_never_tried_twice(fake, monkeypatch):
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche",))
    browser_ = fake(PlaywrightError("Page.goto: net::ERR_CONNECTION_RESET"))
    from backend.models import StoreSelection
    from backend.services import settings

    async def scenario():
        await settings.set_store("intermarche", StoreSelection(id="06814", name="Lattes"))
        return await search.search_store("intermarche", "farine")

    assert run(scenario()).status == "error"
    assert len(browser_.calls) == 1 and browser_.resets == []


def test_no_retry_after_a_check(fake):
    browser_ = fake(BlockedError("Carrefour demande une vérification"))
    assert run(search.search_store("carrefour", "farine")).status == "blocked"
    assert len(browser_.calls) == 1


def test_technical_details_stay_in_the_log(fake, caplog):
    fake(RuntimeError("KeyError: 'gridbox' at line 12\nTraceback (most recent call last)"))
    with caplog.at_level("ERROR", logger="prixmalin.search"):
        result = run(search.search_store("lidl", "farine"))
    assert result.message == "La recherche sur Lidl a échoué. Réessayez dans un instant."
    assert any("gridbox" in r.getMessage() for r in caplog.records)


def test_time_limit_per_retailer(fake, monkeypatch):
    monkeypatch.delenv("PRIXMALIN_TIMEOUT", raising=False)
    monkeypatch.delenv("PRIXMALIN_TIMEOUT_ALDI", raising=False)
    monkeypatch.delenv("PRIXMALIN_TIMEOUT_COURSESU", raising=False)
    monkeypatch.setattr(config, "SCRAPER_TIMEOUT_SECONDS", 40.0)
    assert config.scraper_timeout("aldi") == 40
    assert config.scraper_timeout("coursesu") == 60  # visits the store page first
    monkeypatch.setenv("PRIXMALIN_TIMEOUT_ALDI", "12")
    assert config.scraper_timeout("aldi") == 12
    monkeypatch.setenv("PRIXMALIN_TIMEOUT_ALDI", "abc")
    assert config.scraper_timeout("aldi") == 40
    monkeypatch.setenv("PRIXMALIN_TIMEOUT", "25")
    monkeypatch.setattr(config, "SCRAPER_TIMEOUT_SECONDS", 25.0)
    assert config.scraper_timeout("coursesu") == 25  # PRIXMALIN_TIMEOUT wins over the defaults

    browser_ = fake([])
    monkeypatch.setenv("PRIXMALIN_TIMEOUT_LIDL", "17")
    run(search.search_store("lidl", "farine", priority="basket"))
    assert browser_.calls == [{"key": "lidl", "timeout": 17.0, "priority": "basket"}]


def test_error_kinds():
    assert is_timeout_error(TimeoutError())
    assert is_timeout_error(PlaywrightTimeout("x"))
    assert not is_timeout_error(PlaywrightError("x"))
    assert is_navigation_error(PlaywrightError("net::ERR_CONNECTION_RESET"))
    assert is_navigation_error(PlaywrightError("Execution context was destroyed"))
    assert not is_navigation_error(PlaywrightTimeout("Navigation timeout of 30000 ms exceeded"))
    assert not is_navigation_error(ValueError("Expecting value"))
    assert not is_navigation_error(KeyError("produits"))
