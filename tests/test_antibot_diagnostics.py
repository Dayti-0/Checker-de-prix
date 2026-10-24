"""Anti-bot answers read right, and kept for the diagnostic (user report of October 2026).

- Intermarché: a refusal of its API without any DataDome mark is not a check to
  validate in the window; its raw answer is kept in data/debug.
- Courses U: Cloudflare said « Vérification réussie » but stayed on « En attente
  de la réponse de www.coursesu.com »: the page is reloaded once.
"""

import asyncio
import json

import pytest

from backend import config
from backend.browser import BrowserManager, BrowserUnavailable
from backend.models import StoreSelection
from backend.scrapers import common, intermarche
from backend.scrapers.base import BlockedError, HardBlockError, ScraperError
from backend.scrapers.common import FetchResult
from tests import fixtures
from tests.conftest import browser_missing

# ---------------------------------------------------------------- Intermarché


@pytest.mark.parametrize("status", [401, 403, 405])
def test_a_refusal_without_datadome_is_not_a_check_to_validate(status):
    with pytest.raises(ScraperError) as error:
        intermarche.check_answer(status, '{"message":"Forbidden"}')
    assert not isinstance(error.value, BlockedError)
    assert error.value.status == "error"
    assert str(error.value) == intermarche.REFUSED_MESSAGE
    assert "Ouvrir le site" not in str(error.value)


def test_datadome_answers_are_still_checks_or_blocks():
    with pytest.raises(BlockedError) as captcha:
        intermarche.check_answer(403, json.dumps(fixtures.DATADOME_CAPTCHA_JSON))
    assert not isinstance(captcha.value, HardBlockError)
    with pytest.raises(HardBlockError):
        intermarche.check_answer(403, json.dumps(fixtures.DATADOME_BLOCK_JSON))
    with pytest.raises(HardBlockError):
        intermarche.check_answer(403, "<h1>Accès temporairement restreint</h1>")


def test_the_record_of_a_refusal_holds_no_address():
    result = FetchResult(403, "application/json", '{"message":"Forbidden"}', "https://www.intermarche.com/api/x/06814")
    record = json.loads(intermarche.refusal_record(result))
    assert record == {"status": 403, "content_type": "application/json", "body": '{"message":"Forbidden"}'}
    assert "06814" not in intermarche.refusal_record(result)  # the store stays private


def test_a_refused_search_is_kept_for_the_diagnostic(monkeypatch):
    scraper = intermarche.IntermarcheScraper()

    async def nothing(*args, **kwargs):
        return None

    async def headers(page, service):
        return {}

    async def refused(page, url, method="GET", headers=None, json_body=None, timeout_ms=15000):
        return FetchResult(403, "application/json; charset=utf-8", '{"message":"Forbidden"}', url)

    monkeypatch.setattr(scraper, "_open_site", nothing)
    monkeypatch.setattr(scraper, "_headers", headers)
    monkeypatch.setattr(intermarche, "page_fetch", refused)
    with pytest.raises(ScraperError) as error:
        asyncio.run(scraper.search(object(), "farine", StoreSelection(id="06814", name="Lattes")))
    assert not isinstance(error.value, BlockedError)
    saved = sorted(config.DEBUG_DIR.glob("intermarche-*-refused.json"))
    assert saved
    assert json.loads(saved[-1].read_text(encoding="utf-8"))["status"] == 403


# ---------------------------------------------------------------- Courses U (Cloudflare)

PASSED_PAGE = """<!DOCTYPE html><html><head><title>Un instant…</title>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></head><body>
<div id="challenge-running"></div>
<p>www.coursesu.com</p><p>Vérification de sécurité en cours</p>
<p>Vérification réussie. En attente de la réponse de www.coursesu.com.</p>
<div class="ray-id">Ray ID: a4be0b0299d9169b</div></body></html>"""
STUCK_PAGE = PASSED_PAGE.replace("Vérification réussie. En attente de la réponse de www.coursesu.com.", "")
REAL_PAGE = "<!DOCTYPE html><html><head><title>Courses U</title></head><body>Recherche</body></html>"


def test_a_passed_check_is_recognised():
    assert common.challenge_passed("Vérification réussie. En attente de la réponse de www.coursesu.com.")
    assert common.challenge_passed("Verification successful. Waiting for www.coursesu.com to respond")
    assert not common.challenge_passed("Vérification de sécurité en cours")
    assert not common.challenge_passed(None)


@pytest.fixture(scope="module")
def manager(tmp_path_factory):
    m = BrowserManager(tmp_path_factory.mktemp("profile"))

    async def probe(page):
        return True

    try:
        asyncio.run(m.run("probe", probe, timeout=60))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")
    yield m
    asyncio.run(m.shutdown())


def open_with(manager, pages):
    """Open www.coursesu.com, served ``pages`` in turn (the last one repeated), then wait for clearance."""
    served = []

    async def scenario(page):
        await page.route("**/*", lambda route: route.abort())  # nothing leaves the browser

        async def site(route):
            body = pages[min(len(served), len(pages) - 1)]
            served.append(route.request.url)
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)

        await page.route("https://www.coursesu.com/recherche*", site)
        await page.goto("https://www.coursesu.com/recherche?q=farine", wait_until="domcontentloaded")
        try:
            await common.wait_for_clearance(page, "Courses U")
        except BlockedError as e:
            return "blocked", str(e)
        return "ok", await page.title()

    return asyncio.run(manager.run("coursesu", scenario, timeout=60)), served


def test_a_passed_check_that_waits_is_reloaded_once(manager, monkeypatch):
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(common, "PASSED_RELOAD_AFTER_SECONDS", 1)
    monkeypatch.setattr(common, "CHALLENGE_WAIT_SECONDS", 6)
    (state, title), served = open_with(manager, [PASSED_PAGE, REAL_PAGE])
    assert (state, title) == ("ok", "Courses U")
    assert len(served) == 2  # the page and its reload


def test_a_check_still_running_is_not_reloaded(manager, monkeypatch):
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(common, "PASSED_RELOAD_AFTER_SECONDS", 1)
    monkeypatch.setattr(common, "CHALLENGE_WAIT_SECONDS", 3)
    (state, _), served = open_with(manager, [STUCK_PAGE])
    assert state == "blocked"
    assert len(served) == 1  # never reloaded: the check is still running
