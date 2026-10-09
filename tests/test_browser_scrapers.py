"""End-to-end scraper tests in a real headless Chromium.

The retailer sites are replaced by the pages and API responses of
tests/fixtures.py (Playwright request interception), so these tests check the
scraper code paths, not the live sites.
"""

import asyncio
import json
import re

import pytest

from backend import config
from backend.browser import BrowserManager, BrowserUnavailable
from backend.models import StoreSelection
from backend.scrapers import SCRAPERS, common
from backend.scrapers.base import BlockedError, StoreRequiredError
from tests import fixtures
from tests.conftest import browser_missing


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


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(common, "CHALLENGE_WAIT_SECONDS", 1)


def html(body):
    return lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


def as_json(data, status=200):
    return lambda route: route.fulfill(status=status, content_type="application/json", body=json.dumps(data))


async def offline(page):
    """Nothing may leave the browser during the tests."""
    await page.route("**/*", lambda route: route.abort())


def run_scenario(manager, key, scenario):
    return asyncio.run(manager.run(key, scenario, timeout=60))


def test_aldi_product_tiles(manager):
    async def scenario(page):
        await offline(page)
        await page.route(re.compile(r"https://www\.aldi\.fr/recherche\.html.*"), html(fixtures.ALDI_PAGE))
        return await SCRAPERS["aldi"].search(page, "farine", None)

    products = run_scenario(manager, "aldi-tiles", scenario)
    assert [(p.name, p.price) for p in products] == [
        ("Farine de blé T55", 0.79),
        ("Farine de sarrasin", 1.49),
        ("Gâteau marbré", 2.19),
    ]
    first = products[0]
    assert first.brand == "BELBAKE"
    assert first.quantity_label == "1 kg"
    assert first.unit_price_label == "1 kg = 0,79 €"
    assert first.image_url == "https://www.aldi.fr/img/farine.jpg"
    assert first.product_url == "https://www.aldi.fr/produits/epicerie/farine-de-ble-t55.html"


def test_carrefour_json_api(manager):
    seen = {}

    async def scenario(page):
        await offline(page)

        async def search(route, request):
            seen["xhr"] = request.headers.get("x-requested-with")
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(fixtures.CARREFOUR_SEARCH))

        await page.route("https://www.carrefour.fr/", html(fixtures.HOME_PAGE))
        await page.route(re.compile(r"https://www\.carrefour\.fr/s\?q=.*"), search)
        return await SCRAPERS["carrefour"].search(page, "farine", None)

    products = run_scenario(manager, "carrefour-json", scenario)
    assert seen["xhr"] == "XMLHttpRequest"
    assert [(p.name, p.price) for p in products] == [("Farine de blé T45", 0.85), ("Farine de blé fluide T45", 1.89)]


def test_carrefour_falls_back_to_the_page(manager):
    async def scenario(page):
        await offline(page)

        async def search(route, request):
            if request.headers.get("x-requested-with"):
                await route.fulfill(status=403, content_type="text/html", body="cf-mitigated")
            else:
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=fixtures.CARREFOUR_PAGE)

        await page.route("https://www.carrefour.fr/", html(fixtures.HOME_PAGE))
        await page.route(re.compile(r"https://www\.carrefour\.fr/s\?q=.*"), search)
        return await SCRAPERS["carrefour"].search(page, "farine", None)

    products = run_scenario(manager, "carrefour-page", scenario)
    assert [(p.name, p.price) for p in products] == [
        ("Farine de blé T45 CARREFOUR CLASSIC'", 0.85),
        ("Farine fluide FRANCINE", 1.89),
    ]
    assert products[0].unit_price_label == "0,85 € / KG"
    assert products[0].product_url == "https://www.carrefour.fr/p/farine-de-ble-t45-carrefour-classic-3560070472888"


INTERMARCHE_HOME = """<!DOCTYPE html><html><head><title>Intermarché</title><script>
document.cookie = 'itm_device_id=' + encodeURIComponent(JSON.stringify({id: 'dev-1'})) + '; path=/';
document.cookie = 'itm_usid=sess-1; path=/';
%s
</script></head><body>Accueil</body></html>"""


def test_intermarche_api_with_configured_store(manager):
    seen = {}

    async def scenario(page):
        await offline(page)

        async def api(route, request):
            seen.update(url=request.url, headers=request.headers, body=json.loads(request.post_data))
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(fixtures.INTERMARCHE_SEARCH))

        await page.route("https://www.intermarche.com/", html(INTERMARCHE_HOME % ""))
        await page.route("https://www.intermarche.com/api/service/produits/**", api)
        return await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))

    products = run_scenario(manager, "itm-api", scenario)
    assert [p.name for p in products] == ["Farine de blé T45", "Farine de sarrasin bio"]
    assert "/pdvs/06814/products/byKeywordAndCategory" in seen["url"]
    assert seen["headers"]["x-itm-device-fp"] == "dev-1"
    assert seen["headers"]["x-itm-session-id"] == "sess-1"
    assert seen["headers"]["x-service-name"] == "produits"
    assert seen["body"]["keyword"] == "farine"


def test_intermarche_store_chosen_on_the_site(manager):
    seen = {}

    async def scenario(page):
        await offline(page)

        async def api(route, request):
            seen["url"] = request.url
            await route.fulfill(status=200, content_type="application/json", body=json.dumps({"produits": []}))

        await page.route("https://www.intermarche.com/", html(INTERMARCHE_HOME % "localStorage.setItem('itm-store', '08012');"))
        await page.route("https://www.intermarche.com/api/service/produits/**", api)
        return await SCRAPERS["intermarche"].search(page, "farine", None)

    assert run_scenario(manager, "itm-storage", scenario) == []
    assert "/pdvs/08012/" in seen["url"]


def test_intermarche_requires_a_store(manager):
    async def scenario(page):
        await offline(page)
        # The profile is shared by the tests: forget the store chosen in a previous one
        await page.route("https://www.intermarche.com/", html(INTERMARCHE_HOME % "localStorage.clear();"))
        return await SCRAPERS["intermarche"].search(page, "farine", None)

    with pytest.raises(StoreRequiredError):
        run_scenario(manager, "itm-nostore", scenario)


def test_intermarche_blocked_by_datadome(manager):
    async def scenario(page):
        await offline(page)
        await page.route("https://www.intermarche.com/", html(INTERMARCHE_HOME % ""))
        await page.route("https://www.intermarche.com/api/**", as_json({"url": "https://geo.captcha-delivery.com/"}, 403))
        return await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))

    with pytest.raises(BlockedError):
        run_scenario(manager, "itm-403", scenario)


def test_challenge_page_is_reported(manager):
    async def scenario(page):
        await offline(page)
        await page.route("https://www.intermarche.com/", html(fixtures.DATADOME_PAGE))
        return await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))

    with pytest.raises(BlockedError):
        run_scenario(manager, "itm-captcha", scenario)


def test_intermarche_store_finder(manager):
    async def scenario(page):
        await offline(page)
        await page.route("https://www.intermarche.com/", html(INTERMARCHE_HOME % ""))
        await page.route("https://www.intermarche.com/api/service/pdvs/**", as_json(fixtures.INTERMARCHE_STORES))
        return await SCRAPERS["intermarche"].find_stores(page, 43.6, 3.87)

    stores = run_scenario(manager, "itm-stores", scenario)
    assert [s.id for s in stores] == ["06814", "08012"]


def test_lidl_json_api(manager):
    async def scenario(page):
        await offline(page)
        await page.route("https://www.lidl.fr/", html(fixtures.HOME_PAGE))
        await page.route(re.compile(r"https://www\.lidl\.fr/q/api/search.*"), as_json(fixtures.LIDL_SEARCH))
        return await SCRAPERS["lidl"].search(page, "farine", None)

    products = run_scenario(manager, "lidl", scenario)
    assert [(p.name, p.price) for p in products] == [("Farine de blé T55", 0.75), ("Farine de seigle", 1.29)]


def test_coursesu_visits_store_page_then_searches(manager):
    visited = []

    async def scenario(page):
        await offline(page)

        def track(body):
            async def handler(route, request):
                visited.append(request.url)
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)
            return handler

        await page.route("https://www.coursesu.com/drive-superu-roujan", track(fixtures.HOME_PAGE))
        await page.route(re.compile(r"https://www\.coursesu\.com/recherche.*"), track(fixtures.COURSESU_PAGE))
        store = StoreSelection(url="https://www.coursesu.com/drive-superu-roujan", name="Super U Roujan")
        return await SCRAPERS["coursesu"].search(page, "farine", store)

    products = run_scenario(manager, "coursesu", scenario)
    assert visited[0] == "https://www.coursesu.com/drive-superu-roujan"
    assert visited[1].startswith("https://www.coursesu.com/recherche?q=farine")
    first = products[0]
    assert (first.name, first.price, first.promo) == ("Farine de blé T45 U, 1kg", 0.95, "Au lieu de 1,10 €")
    assert first.unit_price_label == "0,95 € / kg"
    assert first.image_url == "https://www.coursesu.com/images/farine-u.jpg"
    assert first.product_url == "https://www.coursesu.com/p/farine-de-ble-t45-u/123.html"
    assert products[1].price == 1.75


def test_timeout_releases_the_retailer_tab(manager):
    async def slow(page):
        await asyncio.sleep(5)

    async def quick(page):
        return "ok"

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(manager.run("timeout", slow, timeout=0.5))
    assert asyncio.run(manager.run("timeout", quick, timeout=5)) == "ok"
