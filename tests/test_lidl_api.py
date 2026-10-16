"""Lidl: the search API asked like lidl.fr does, answers without products, page tiles.

The API of Lidl refuses ``Accept: application/json`` (HTTP 406, seen on lidl.es,
.ie and .pt in 2026): the simulated site below does the same.
"""

import asyncio
import json
import re

import pytest

from backend import config
from backend.browser import BrowserManager, BrowserUnavailable
from backend.models import Product
from backend.scrapers import SCRAPERS, common, lidl
from backend.services import health
from backend.services.search import final_status
from tests import fixtures
from tests.conftest import browser_missing

SCRAPER = SCRAPERS["lidl"]
API = re.compile(r"https://www\.lidl\.fr/q/api/search.*")
SEARCH_PAGE = re.compile(r"https://www\.lidl\.fr/q/search.*")
GRID = {
    "fullTitle": "Farine de blé T45",
    "price": {"price": 0.69, "basePrice": {"text": "1 kg (1 kg = 0,69 €)"}},
    "canonicalUrl": "/p/belbake-farine-de-ble-t45/p100000001",
    "productId": 100000001,
}


# ---------------------------------------------------------------- pure functions


def test_empty_answers():
    assert lidl.is_empty_answer({"items": [], "numFound": 0})
    assert lidl.is_empty_answer({"resultType": "empty"})  # no list of items at all
    assert lidl.is_empty_answer({"numFound": 0})
    assert not lidl.is_empty_answer({"items": [{"gridbox": {"data": GRID}}]})
    assert not lidl.is_empty_answer({"resultType": "redirect", "redirectURL": "/c/farine/s1"})
    assert not lidl.is_empty_answer({"error": "bad request"})
    assert not lidl.is_empty_answer(None)


def test_redirects_stay_on_lidl_fr():
    assert lidl.redirect_url({"resultType": "redirect", "redirectURL": "/c/farines/s10012"}) == (
        "https://www.lidl.fr/c/farines/s10012"
    )
    assert lidl.redirect_url({"resultType": "redirect", "redirectURL": "https://evil.example/x"}) is None
    assert lidl.redirect_url({"resultType": "redirect", "redirectURL": "//evil.example/x"}) is None
    assert lidl.redirect_url({"resultType": "redirect"}) is None
    assert lidl.redirect_url({"items": []}) is None


def test_tiles_of_a_page_and_titles():
    attributes = [json.dumps(GRID), None, "pas du json", json.dumps([1, 2])]
    products = lidl.parse_search_json(lidl.grid_items(attributes))
    assert [(p.name, p.price, p.sku) for p in products] == [("Farine de blé T45", 0.69, "100000001")]
    soft = {**GRID, "fullTitle": "Fa­rine de bl&eacute; T55​"}
    assert lidl.parse_search_json({"items": [{"gridbox": {"data": soft}}]})[0].name == "Farine de blé T55"


def test_message_when_lidl_has_no_such_product_online():
    status, message = final_status(SCRAPER, None, [], "api")
    assert status == "empty" and message == lidl.EMPTY_MESSAGE
    assert "offres de la semaine" in message
    # Not read from the API (fallback page, test double): the usual message
    assert final_status(SCRAPER, None, [], None) == ("empty", "Aucun produit trouvé chez Lidl.")
    product = Product(store="lidl", name="Farine", price=1.0)
    assert final_status(SCRAPER, None, [product], "api") == ("ok", None)


def health_row(status, query, source=None):
    return {
        "ts": 1_800_000_000.0,
        "store": "lidl",
        "store_ctx": "",
        "query": query,
        "status": status,
        "source": source,
        "products": 0,
        "priced": 0,
        "elapsed_ms": 900,
        "error": "Aucun produit",
        "from_cache": 0,
    }


def test_empty_answers_of_the_api_are_not_a_breakage():
    """lidl.fr publishes few foods: « nothing » answered by its API is not « Probablement cassé »."""
    answered = [health_row("empty", q, "api") for q in ("farine", "lait", "sucre")]
    assert health.retailer_health("lidl", answered, 1_800_000_100.0).state == "ok"
    # Nothing read at all, three different queries: broken, as before
    failed = [health_row("empty", q) for q in ("farine", "lait", "sucre")]
    assert health.retailer_health("lidl", failed, 1_800_000_100.0).state == "broken"


# ---------------------------------------------------------------- in Chromium


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


def lidl_api(answer, seen):
    """The search API of Lidl: HTTP 406 to a bare application/json, like the real one."""

    async def handler(route, request):
        accept = request.headers.get("accept", "")
        seen.append(accept)
        if accept.strip() == "application/json":
            await route.fulfill(status=406, content_type="text/plain", body="Not Acceptable")
            return
        await route.fulfill(
            status=200, content_type="application/mindshift.search+json;version=2", body=json.dumps(answer)
        )

    return handler


def tiles_page(*grids):
    tiles = "".join(
        f"<div class='product-grid-box' data-grid-data='{json.dumps(g).replace(chr(39), '&#39;')}'></div>"
        for g in grids
    )
    return f"<!DOCTYPE html><html><head><title>Lidl</title></head><body>{tiles}</body></html>"


def search(manager, routes, query="farine"):
    async def scenario(page):
        await page.route("**/*", lambda route: route.abort())  # nothing leaves the browser
        await page.route("https://www.lidl.fr/", html(fixtures.HOME_PAGE))
        for pattern, handler in routes:
            await page.route(pattern, handler)
        products = await SCRAPER.search(page, query, None)
        return products, SCRAPER.last_source

    return asyncio.run(manager.run("lidl", scenario, timeout=60))


def test_the_api_is_asked_like_lidl_fr_does(manager):
    seen = []
    products, source = search(manager, [(API, lidl_api(fixtures.LIDL_SEARCH, seen))])
    assert [(p.name, p.price) for p in products] == [("Farine de blé T55", 0.75), ("Farine de seigle", 1.29)]
    assert source == "api"
    assert seen and all("application/mindshift.search+json" in a for a in seen)


def test_no_product_online_is_a_real_answer_kept_as_proof(manager):
    pages = []

    async def page_visit(route):
        pages.append(route.request.url)
        await route.fulfill(status=200, content_type="text/html", body=tiles_page())

    seen = []
    products, source = search(manager, [(API, lidl_api({"items": [], "numFound": 0}, seen)), (SEARCH_PAGE, page_visit)])
    assert products == [] and source == "api"
    assert pages == []  # the API answered: the page is not read
    saved = sorted(config.DEBUG_DIR.glob("lidl-*-empty.json"))
    assert saved and json.loads(saved[-1].read_text(encoding="utf-8")) == {"items": [], "numFound": 0}


def test_without_the_api_the_tiles_of_the_page_are_read(manager):
    async def refused(route):
        await route.fulfill(status=406, content_type="text/plain", body="Not Acceptable")

    products, source = search(manager, [(API, refused), (SEARCH_PAGE, html(tiles_page(GRID)))])
    assert [(p.name, p.price, p.unit_price_label) for p in products] == [("Farine de blé T45", 0.69, "1 kg = 0,69 €")]
    assert source == "html"
    assert sorted(config.DEBUG_DIR.glob("lidl-*-error.txt"))  # the refusal is kept


def test_a_redirect_of_the_api_is_followed_on_lidl_fr(manager):
    seen = []
    redirect = {"resultType": "redirect", "redirectURL": "/c/farines/s10012"}
    routes = [
        (API, lidl_api(redirect, seen)),
        ("https://www.lidl.fr/c/farines/s10012", html(tiles_page(GRID))),
    ]
    products, source = search(manager, routes)
    assert [p.name for p in products] == ["Farine de blé T45"] and source == "html"
