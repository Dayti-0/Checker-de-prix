"""E.Leclerc Drive scraper in a real headless Chromium, the site replaced by tests/fixtures (P8).

The dedicated Chrome window is not started here: the scraper gets a Chromium
tab whose requests are answered by ``page.route`` (nothing leaves the browser).
The window itself is covered by tests/test_p3_real_chrome.py.
"""

import asyncio
import json
import re

import pytest

from backend import config
from backend.browser import BrowserManager, BrowserUnavailable
from backend.models import StoreSelection
from backend.scrapers import common
from backend.scrapers import leclerc as lc
from backend.scrapers.base import BlockedError, HardBlockError, StoreRequiredError
from tests import fixtures
from tests.conftest import browser_missing

BRUGES = StoreSelection(id="173301", name="E.Leclerc Drive Bruges", url=fixtures.LECLERC_BASE)
SEARCH = re.compile(r"https://fd12-courses\.leclercdrive\.fr/magasin-173301-173301-Bruges/recherche\.aspx\?.*")
HOME = fixtures.LECLERC_HOME_URL
PORTAL = "https://www.leclercdrive.fr/"
LOCATOR = re.compile(r"https://api-recherchemagasins\.leclercdrive\.fr/API_RechercheMagasins/api/v1/.*")
CORS = {"access-control-allow-origin": PORTAL.rstrip("/"), "access-control-allow-credentials": "true"}


@pytest.fixture(scope="module")
def manager(tmp_path_factory):
    m = BrowserManager(tmp_path_factory.mktemp("profile-p8"))

    async def probe(page):
        return True

    try:
        asyncio.run(m.run("probe", probe, timeout=60))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")
    yield m
    asyncio.run(m.shutdown())


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(config, "REAL_CHROME_SETTLE_SECONDS", 0)
    monkeypatch.setattr(common, "CHALLENGE_WAIT_SECONDS", 1)
    monkeypatch.setattr(lc, "LOCATOR_PAUSE_SECONDS", 0)


def redirect_to(url):
    """The site sends the tab elsewhere. A redirection fulfilled by ``route`` is not followed by
    Chromium (it goes to the network), so the page itself moves on, before its first paint."""
    return html(f"<html><head><script>location.replace({json.dumps(url)})</script></head><body></body></html>")


def html(body, status=200):
    async def handler(route):
        await route.fulfill(status=status, content_type="text/html; charset=utf-8", body=body)

    return handler


async def offline(page):
    """Nothing may leave the browser during the tests."""
    await page.route("**/*", lambda route: route.abort())


def run_scenario(manager, key, scenario):
    """``key``: a tab of the shared Chromium of the test (not the dedicated window of « leclerc »)."""
    return asyncio.run(manager.run(key, scenario, timeout=60))


def counter(handler, seen: list):
    async def counted(route, request):
        seen.append(request.url)
        await handler(route)

    return counted


def test_visit_then_search_in_the_page(manager):
    scraper = lc.LeclercScraper()
    visits, searches = [], []

    async def scenario(page):
        await offline(page)
        await page.route(HOME, counter(html(fixtures.LECLERC_HOME_HTML), visits))
        await page.route(SEARCH, counter(html(fixtures.LECLERC_SEARCH_HTML), searches))
        first = await scraper.search(page, "coca cola 1,75 l", BRUGES)
        source = scraper.last_source
        second = await scraper.search(page, "eau", BRUGES)
        return first, source, second, page.url

    first, source, second, url = run_scenario(manager, "leclerc-visit", scenario)
    assert len(first) == 20 and len(second) == 20 and source == "api"
    assert (first[0].sku, first[0].price) == ("214087", 2.38)
    # One visit of the drive for two searches close together, made with fetch() (the tab stays on the drive)
    assert visits == [HOME]
    assert [s.split("=", 1)[1] for s in searches] == ["coca%20cola%201%2C75%20l", "eau"]
    assert url == HOME


def test_visit_redirected_to_another_host(manager):
    """The generic host fd1 sends to the host of the drive (fd10): the searches go there."""
    scraper = lc.LeclercScraper()
    reims = StoreSelection(id="085111", url="https://fd1-courses.leclercdrive.fr/magasin-085111-085111-Reims")
    seen = []

    async def scenario(page):
        await offline(page)

        await page.route(
            "https://fd1-courses.leclercdrive.fr/magasin-085111-085111-Reims.aspx",
            redirect_to("https://fd10-courses.leclercdrive.fr/magasin-085111-085111-Reims.aspx"),
        )
        await page.route("https://fd10-courses.leclercdrive.fr/magasin-085111-085111-Reims.aspx", html("<p>Reims</p>"))
        await page.route(
            re.compile(r"https://fd10-courses\.leclercdrive\.fr/magasin-085111-085111-Reims/recherche\.aspx\?.*"),
            counter(html(fixtures.LECLERC_SEARCH_HTML), seen),
        )
        return await scraper.search(page, "cola", reims)

    products = run_scenario(manager, "leclerc-fd10", scenario)
    assert len(products) == 20
    assert seen == [
        "https://fd10-courses.leclercdrive.fr/magasin-085111-085111-Reims/recherche.aspx?TexteRecherche=cola"
    ]
    assert all(p.product_url.startswith("https://fd12-courses.leclercdrive.fr/") for p in products)


def test_refused_fetch_loads_the_search_page(manager):
    """fetch() refused (redirection elsewhere): the drive is visited again, then the search loaded as a page."""
    scraper = lc.LeclercScraper()
    visits, searches = [], []

    async def scenario(page):
        await offline(page)
        await page.route(HOME, counter(html(fixtures.LECLERC_HOME_HTML), visits))

        async def search(route, request):
            searches.append(request.resource_type)
            if request.resource_type == "fetch":
                await route.abort()
            else:
                await route.fulfill(
                    status=200, content_type="text/html; charset=utf-8", body=fixtures.LECLERC_SEARCH_HTML
                )

        await page.route(SEARCH, search)
        return await scraper.search(page, "cola", BRUGES), scraper.last_source

    products, source = run_scenario(manager, "leclerc-refused", scenario)
    assert len(products) == 20 and source == "api"
    assert visits == [HOME, HOME]
    assert searches == ["fetch", "document"]


def test_expired_session_then_tiles_of_the_page(manager):
    """« Session expirée »: one new visit and the page loaded; without its JSON, its tiles are read."""
    scraper = lc.LeclercScraper()
    page_without_json = re.sub(r"//<!\[CDATA\[[\s\S]*?//\]\]>", "", fixtures.LECLERC_TILES_HTML)
    assert "pnlElementProduit'" not in page_without_json
    searches = []

    async def scenario(page):
        await offline(page)
        await page.route(HOME, html(fixtures.LECLERC_HOME_HTML))

        async def search(route, request):
            searches.append(request.resource_type)
            body = fixtures.LECLERC_SESSION_HTML if request.resource_type == "fetch" else page_without_json
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)

        await page.route(SEARCH, search)
        return await scraper.search(page, "coca", BRUGES), scraper.last_source

    products, source = run_scenario(manager, "leclerc-session", scenario)
    assert searches == ["fetch", "document"]
    assert source == "html"
    assert len(products) == 6
    assert (products[0].name, products[0].quantity_label, products[0].price) == (
        "Soda Coca-Cola Original",
        "1,75L",
        2.38,
    )
    assert products[0].image_url.startswith("https://fd12-photos.leclercdrive.fr/image.ashx?id=")
    promo = next(p for p in products if p.old_price)
    assert (promo.price, promo.old_price, promo.unit_price_label) == (8.72, 10.22, "0,83 € / l")
    assert sum(not p.available for p in products) == 1


def test_closed_drive_leads_to_the_portal(manager):
    scraper = lc.LeclercScraper()

    async def scenario(page):
        await offline(page)

        await page.route(HOME, redirect_to(PORTAL))
        await page.route(PORTAL, html(fixtures.LECLERC_PORTAL_HTML))
        with pytest.raises(StoreRequiredError) as error:
            await scraper.search(page, "farine", BRUGES)
        return str(error.value)

    assert run_scenario(manager, "leclerc-gone", scenario) == lc.STORE_GONE


def test_without_drive_or_with_a_wrong_address(manager):
    scraper = lc.LeclercScraper()

    async def scenario(page):
        await offline(page)
        with pytest.raises(StoreRequiredError) as missing:
            await scraper.search(page, "farine", None)
        with pytest.raises(StoreRequiredError) as wrong:
            await scraper.search(page, "farine", StoreSelection(id="1", url="https://www.leclercdrive.fr/"))
        return str(missing.value), str(wrong.value), page.url

    missing, wrong, url = run_scenario(manager, "leclerc-nostore", scenario)
    assert missing == lc.STORE_MISSING and wrong == lc.STORE_GONE
    assert url == "about:blank"  # nothing was loaded


def test_captcha_at_the_visit_is_reported_without_reload(manager):
    scraper = lc.LeclercScraper()
    visits = []

    async def scenario(page):
        await offline(page)
        await page.route(HOME, counter(html(fixtures.LECLERC_CAPTCHA_HTML, 403), visits))
        with pytest.raises(BlockedError) as error:
            await scraper.search(page, "farine", BRUGES)
        return error.value

    error = run_scenario(manager, "leclerc-captcha", scenario)
    assert str(error) == lc.CAPTCHA_MESSAGE and not isinstance(error, HardBlockError)
    assert visits == [HOME]


def test_hard_block_of_the_search(manager):
    scraper = lc.LeclercScraper()
    searches = []

    async def scenario(page):
        await offline(page)
        await page.route(HOME, html(fixtures.LECLERC_HOME_HTML))
        await page.route(SEARCH, counter(html(fixtures.LECLERC_HARD_BLOCK_HTML, 403), searches))
        with pytest.raises(HardBlockError):
            await scraper.search(page, "farine", BRUGES)

    run_scenario(manager, "leclerc-hard", scenario)
    assert len(searches) == 1  # never retried


def test_no_product_keeps_the_page(manager):
    scraper = lc.LeclercScraper()

    async def scenario(page):
        await offline(page)
        await page.route(HOME, html(fixtures.LECLERC_HOME_HTML))
        await page.route(SEARCH, html(fixtures.LECLERC_EMPTY_HTML))
        return await scraper.search(page, "zzqx", BRUGES)

    assert run_scenario(manager, "leclerc-empty", scenario) == []
    assert scraper.last_source is None
    saved = list(config.DEBUG_DIR.glob("leclerc-*-empty.html"))
    assert len(saved) == 1 and "pnlElementProduit" in saved[0].read_text(encoding="utf-8")


def test_debug_samples(manager, monkeypatch):
    monkeypatch.setenv("PRIXMALIN_DEBUG_LECLERC", "1")
    scraper = lc.LeclercScraper()

    async def scenario(page):
        await offline(page)
        await page.route(HOME, html(fixtures.LECLERC_HOME_HTML))
        await page.route(SEARCH, html(fixtures.LECLERC_SEARCH_HTML))
        return await scraper.search(page, "cola", BRUGES)

    assert len(run_scenario(manager, "leclerc-sample", scenario)) == 20
    assert len(list(config.DEBUG_DIR.glob("leclerc-*-sample.html"))) == 1


def json_answer(data, status=200):
    async def handler(route):
        await route.fulfill(status=status, content_type="application/json", headers=CORS, body=json.dumps(data))

    return handler


def test_find_stores_from_the_portal(manager):
    scraper = lc.LeclercScraper()
    calls = []

    async def scenario(page):
        await offline(page)
        await page.route(PORTAL, html(fixtures.LECLERC_PORTAL_HTML))

        async def locator(route, request):
            calls.append(request.url)
            await json_answer(fixtures.LECLERC_NEARBY)(route)

        await page.route(LOCATOR, locator)
        stores = await scraper.find_stores(page, 43.6119, 3.8772, "34000")
        return stores, page.url

    stores, url = run_scenario(manager, "leclerc-stores", scenario)
    assert url == PORTAL
    assert calls == [lc.LOCATOR_API + "/MapPoint/nearby?latitude=43.6119&longitude=3.8772&postalCode=34000"]
    assert [s.id for s in stores] == ["093401", "093401", "190501", "190601", "190801"]


def test_find_stores_by_postal_code_when_nearby_refuses(manager):
    scraper = lc.LeclercScraper()
    calls = []

    async def scenario(page):
        await offline(page)
        await page.route(PORTAL, html(fixtures.LECLERC_PORTAL_HTML))

        async def locator(route, request):
            path = request.url.split("/api/v1/", 1)[1]
            calls.append(path.split("?", 1)[0])
            if path.startswith("MapPoint/nearby") and len(calls) == 1:
                await json_answer({"message": "Bad request"}, 400)(route)
            elif path.startswith("MapPoint/nearby"):
                await json_answer(fixtures.LECLERC_NEARBY)(route)
            elif path.startswith("autocomplete/coordinates"):
                await json_answer(fixtures.LECLERC_COORDINATES)(route)
            else:
                await json_answer(fixtures.LECLERC_AUTOCOMPLETE)(route)

        await page.route(LOCATOR, locator)
        return await scraper.find_stores(page, 43.6, 3.87, "34000")

    stores = run_scenario(manager, "leclerc-stores-cp", scenario)
    assert calls == ["MapPoint/nearby", "autocomplete", "autocomplete/coordinates", "MapPoint/nearby"]
    assert len(stores) == 5


def test_find_stores_captcha_and_nothing(manager):
    scraper = lc.LeclercScraper()

    async def scenario(page):
        await offline(page)
        await page.route(PORTAL, html(fixtures.LECLERC_PORTAL_HTML))
        await page.route(LOCATOR, json_answer({"url": "https://geo.captcha-delivery.com/captcha/?t=fe&cid=x"}, 403))
        with pytest.raises(BlockedError):
            await scraper.find_stores(page, 43.6, 3.87, "34000")
        await page.unroute(LOCATOR)
        await page.route(LOCATOR, json_answer({"points": []}))
        return await scraper.find_stores(page, None, None, "34000")

    assert run_scenario(manager, "leclerc-stores-bad", scenario) == []
    assert len(list(config.DEBUG_DIR.glob("leclerc-*-stores.json"))) == 1


def test_read_site_store_without_request(manager):
    scraper = lc.LeclercScraper()
    loads = []

    async def scenario(page):
        await offline(page)
        await page.route(HOME, counter(html(fixtures.LECLERC_HOME_HTML), loads))
        await page.goto(HOME)
        await page.context.add_cookies(
            [{"name": "clsWCSD107:ContexteMU", "value": "@d=2%7c173301", "domain": ".leclercdrive.fr", "path": "/"}]
        )
        return await scraper.read_site_store(page)

    info = run_scenario(manager, "leclerc-readback", scenario)
    assert loads == [HOME]  # only the page loaded by the test
    assert info["url"] == HOME and info["cookie"] == "@d=2%7c173301"
    chosen = lc.site_store_selection(info["url"], info["html"], info["cookie"], [])
    assert (chosen.id, chosen.name, chosen.url) == ("173301", "E.Leclerc Drive Bruges", fixtures.LECLERC_BASE)
