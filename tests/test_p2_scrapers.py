"""Scrapers of Aldi, Lidl and Carrefour: barcodes, second page, light thumbnails (B37, B39, B40).

The pure functions are tested directly; the page paths run in a real headless
Chromium against the pages of tests/fixtures (nothing leaves the browser).
"""

import asyncio
import json
import re

import pytest

from backend import config
from backend.browser import BrowserManager, BrowserUnavailable
from backend.models import Product
from backend.scrapers import SCRAPERS, carrefour, common, extract, lidl
from backend.scrapers.extract import (
    PageBudget,
    barcode_of,
    card_to_product,
    first_url,
    identifier_of,
    merge_pages,
    products_from_json,
    products_from_json_ld,
)
from backend.services.products import dedup_key, is_bio, is_store_brand, prepare_products
from tests import fixtures
from tests.conftest import browser_missing

# --- Pure functions -----------------------------------------------------------


def test_carrefour_barcode_identifier_and_thumbnail():
    products = carrefour.parse_search_json(fixtures.CARREFOUR_SEARCH)
    assert [p.ean for p in products] == ["3560070472888", "3229820129488"]
    assert [p.sku for p in products] == ["3560070472888", "3229820129488"]
    # The medium size of the site (280x280) rather than the large one
    assert products[0].image_url == "https://www.carrefour.fr/media/280x280/Photosite/farine.jpg"
    only_large = carrefour.parse_search_json(fixtures.CARREFOUR_SEARCH_PAGE2)[0]
    assert only_large.image_url == "https://www.carrefour.fr/media/280x280/Photosite/3560070123452.jpg"


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://www.carrefour.fr/media/540x540/Photosite/a.jpg",
            "https://www.carrefour.fr/media/280x280/Photosite/a.jpg",
        ),
        ("https://www.carrefour.fr/media/1500x1500/a.jpg", "https://www.carrefour.fr/media/280x280/a.jpg"),
        ("https://www.carrefour.fr/media/280x280/a.jpg", "https://www.carrefour.fr/media/280x280/a.jpg"),
        ("https://www.carrefour.fr/media/120x120/a.jpg", "https://www.carrefour.fr/media/120x120/a.jpg"),
        ("https://www.carrefour.fr/media/a.jpg", "https://www.carrefour.fr/media/a.jpg"),
        (None, None),
    ],
)
def test_carrefour_thumbnail(url, expected):
    assert carrefour.thumbnail(url) == expected


@pytest.mark.parametrize(
    "data, read, expected",
    [
        (fixtures.CARREFOUR_SEARCH, 2, False),  # meta.total = 2
        (fixtures.CARREFOUR_SEARCH_PAGE1, 2, True),  # links.next
        ({"data": [], "meta": {"total": 50}}, 24, True),
        ({"data": [], "meta": {"totalPages": 1}}, 30, False),
        ({"data": [], "meta": {"pagination": {"totalPages": 3}}}, 30, True),
        ({"data": []}, 30, True),  # nothing said: a full page may have a next one
        ({"data": []}, 12, False),
        ({"data": []}, 0, False),
        ("not json", 30, False),
    ],
)
def test_carrefour_has_next_page(data, read, expected):
    assert carrefour.has_next_page(data, read) is expected


def test_lidl_barcode_identifier_old_price_and_next_offset():
    products = lidl.parse_search_json(fixtures.LIDL_SEARCH)
    assert [p.sku for p in products] == ["100012", "100013"]
    assert products[0].old_price == 0.89
    assert products[1].old_price is None
    assert lidl.parse_search_json(fixtures.LIDL_SEARCH_PAGE2)[0].ean == "3200411000010"
    assert lidl.next_offset(fixtures.LIDL_SEARCH_PAGE1) == 2
    assert lidl.next_offset(fixtures.LIDL_SEARCH_PAGE2) is None
    assert lidl.next_offset(fixtures.LIDL_SEARCH) is None  # numFound = items
    assert lidl.next_offset({"numFound": 10, "items": []}) is None


def test_json_ld_barcode_availability_and_image():
    (product,) = products_from_json_ld([fixtures.JSON_LD_PRODUCT], "x", "https://shop.example")
    assert (product.ean, product.sku, product.available) == ("3265478901236", "LES-1L", False)
    assert product.image_url == "https://shop.example/img/huile-tournesol.jpg"
    assert product.brand == "Lesieur"


def test_generic_json_barcodes_and_identifiers():
    data = {
        "hits": [
            {"name": "Farine T55", "price": 0.79, "ean": "3560070472888", "sku": "A1"},
            {"name": "Sucre", "price": 1.05, "gtin13": 3560070472901, "productId": 42},
            {"name": "Sel", "price": 0.5, "barcode": "123"},  # not a barcode
        ]
    }
    products = products_from_json(data, "aldi", "https://www.aldi.fr")
    assert [(p.ean, p.sku) for p in products] == [("3560070472888", "A1"), ("3560070472901", "42"), (None, None)]
    assert barcode_of({"ians": ["bad", "3200411000010"]}) == "3200411000010"
    assert identifier_of({"erpNumber": "0081234"}) == "0081234"
    assert identifier_of({"sku": True}) is None


def test_first_url_prefers_a_light_size():
    assert first_url({"large": "/l.jpg", "medium": "/m.jpg"}) == "/m.jpg"
    assert first_url([{"small": "/s.jpg", "large": "/l.jpg"}]) == "/s.jpg"
    assert first_url({"large": "/l.jpg"}) == "/l.jpg"
    assert first_url({"thumbnail": "/t.jpg", "image": "/i.jpg"}) == "/t.jpg"
    assert (
        products_from_json({"name": "Farine", "price": 1, "image": "/i.jpg", "thumbnail": "/t.jpg"}, "x", "https://e")[
            0
        ].image_url
        == "https://e/t.jpg"
    )


def test_card_barcode_identifier_and_old_price():
    card = {
        "url": "/p/farine",
        "names": ["Farine de blé T45"],
        "priceTexts": ["1,10 €", "0,95 €"],
        "strike": ["1,10 €"],
        "text": "Farine de blé T45 1,10 € 0,95 €",
        "ean": "3560070472888",
        "sku": "123",
    }
    product = card_to_product(card, "coursesu", "https://shop.example")
    assert (product.ean, product.sku, product.old_price, product.promo) == (
        "3560070472888",
        "123",
        1.1,
        "Au lieu de 1,10 €",
    )
    # A product identifier that is a barcode is one
    pid = card_to_product({**card, "ean": None, "sku": "3229820129488"}, "coursesu", "https://shop.example")
    assert pid.ean == "3229820129488"


def test_merge_pages_keeps_each_product_once():
    one = Product(store="x", name="Farine", price=1.0, product_url="https://e/1")
    same = Product(store="x", name="farine", price=1.0, product_url="https://e/1")
    other = Product(store="x", name="Farine", price=1.0, product_url="https://e/2")
    coded = Product(store="x", name="Farine bio", price=2.0, product_url="https://e/3", ean="3560070472888")
    coded_again = Product(store="x", name="Farine bio 1kg", price=2.0, product_url="https://e/4", ean="3560070472888")
    assert merge_pages([one, coded], [same, other, coded_again]) == [one, coded, other]


def test_page_budget_is_half_the_time_of_the_search(monkeypatch):
    now = [100.0]
    budget = PageBudget("carrefour", timeout=10, clock=lambda: now[0])
    assert budget.allows_more()
    now[0] = 104.9
    assert budget.allows_more()
    now[0] = 105.0
    assert not budget.allows_more()
    monkeypatch.setenv("PRIXMALIN_TIMEOUT_LIDL", "8")
    assert PageBudget("lidl").timeout == 8


# --- Duplicates, flags (services/products.py) --------------------------------


def test_dedup_key_barcode_then_page_name_contents_price():
    small = Product(store="x", name="Eau minérale", price=0.5, quantity_label="50 cl", product_url="https://x/")
    pack = Product(store="x", name="Eau minérale", price=2.4, quantity_label="6 x 1,5 L", product_url="https://x/")
    assert dedup_key(small) != dedup_key(pack)
    assert len(prepare_products([small, pack], "eau")) == 2  # both kept

    coded = Product(store="x", name="Eau minérale 6x1,5L", price=2.4, ean="3254381025063")
    assert prepare_products([coded], "eau")[0].ean is None  # wrong check digit: no barcode
    assert dedup_key(coded) == ("item", "", "eau minerale 6x1 5l", "", 2.4)
    good = Product(store="x", name="Eau", price=2.4, ean="3560070472888", product_url="https://x/p/1")
    again = Product(store="x", name="Eau de source", price=2.5, ean="3560070472888", product_url="https://x/p/2")
    assert len(prepare_products([good, again], "eau")) == 1


def test_duplicate_without_price_gives_way():
    ean = "3560070472888"
    no_price = Product(
        store="x", name="Farine", price=None, ean=ean, image_url="https://x/i.jpg", product_url="https://x/1"
    )
    priced = Product(store="x", name="Farine T45", price=0.9, ean=ean, product_url="https://x/2")
    (kept,) = prepare_products([no_price, priced], "farine")
    assert (kept.name, kept.price, kept.image_url) == ("Farine T45", 0.9, "https://x/i.jpg")


@pytest.mark.parametrize(
    "name, brand, expected",
    [
        ("Farine de blé T65 bio", None, True),
        ("Huile d'olive", "Carrefour Bio", True),
        ("Lait demi-écrémé biologique", None, True),
        ("Boisson amande", "Bjorg", True),
        ("Farine de blé", "Francine", False),
        ("Biscottes", None, False),
    ],
)
def test_is_bio(name, brand, expected):
    assert is_bio(Product(store="x", name=name, brand=brand)) is expected


@pytest.mark.parametrize(
    "store, name, brand, expected",
    [
        ("carrefour", "Farine de blé T45", "CARREFOUR CLASSIC'", True),
        ("carrefour", "Farine de blé T45", "Simpl", True),
        ("carrefour", "Farine de blé T45 CARREFOUR CLASSIC'", None, True),
        ("carrefour", "Farine de blé fluide", "FRANCINE", False),
        ("lidl", "Farine de blé T55", "Belbake", True),
        ("lidl", "Lait", "Milbona", True),
        ("aldi", "Lait", "Milsani", True),
        ("intermarche", "Farine", "Chabrior", True),
        ("intermarche", "Beurre doux", "Pâturages", True),
        ("coursesu", "Farine de blé T45 U, 1kg", None, True),
        ("coursesu", "Farine", "U Bio", True),
        ("coursesu", "Pâtes", "Panzani", False),
        ("coursesu", "Pâtes", "Uncle Ben's", False),
        ("aldi", "Gâteau marbré", None, None),
    ],
)
def test_is_store_brand(store, name, brand, expected):
    assert is_store_brand(Product(store=store, name=name, brand=brand)) is expected


def test_unavailable_products_come_last():
    products = [
        Product(store="x", name="Farine A", price=0.5, available=False, product_url="https://x/a"),
        Product(store="x", name="Farine B", price=None, product_url="https://x/b"),
        Product(store="x", name="Farine C", price=0.9, product_url="https://x/c"),
        Product(store="x", name="Gâteau à la farine", price=0.2, product_url="https://x/d"),
    ]
    assert [p.name for p in prepare_products(products, "farine")] == [
        "Farine C",
        "Farine B",
        "Farine A",
        "Gâteau à la farine",
    ]


# --- In Chromium ----------------------------------------------------------------


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
    monkeypatch.setattr(extract, "PAGE_PAUSE_MS", 50)


def html(body):
    return lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


async def offline(page):
    await page.route("**/*", lambda route: route.abort())


def run_scenario(manager, key, scenario):
    return asyncio.run(manager.run(key, scenario, timeout=60))


def json_pages(pages, seen, delay=0.0):
    """Route handler answering page=N (or offset=N) of a search with ``pages[N]``."""

    async def handler(route, request):
        seen.append(request.url)
        number = re.search(r"[?&](?:page|offset)=(\d+)", request.url)
        key = int(number.group(1)) if number else 0
        if delay:
            await asyncio.sleep(delay)
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(pages.get(key, {})))

    return handler


def test_carrefour_reads_page_2_and_merges(manager):
    seen = []

    async def scenario(page):
        await offline(page)
        await page.route("https://www.carrefour.fr/", html(fixtures.HOME_PAGE))
        pages = {1: fixtures.CARREFOUR_SEARCH_PAGE1, 2: fixtures.CARREFOUR_SEARCH_PAGE2}
        await page.route(re.compile(r"https://www\.carrefour\.fr/s\?q=.*"), json_pages(pages, seen))
        return await SCRAPERS["carrefour"].search(page, "farine", None)

    products = run_scenario(manager, "carrefour-pages", scenario)
    assert [p.name for p in products] == ["Farine de blé T45", "Farine de blé fluide T45", "Farine de blé T55"]
    assert [u.split("page=")[1] for u in seen] == ["1", "2"]
    assert SCRAPERS["carrefour"].last_source == "api"
    assert all(p.ean for p in products)


def test_carrefour_slow_first_page_stops_there(manager, monkeypatch):
    monkeypatch.setenv("PRIXMALIN_TIMEOUT_CARREFOUR", "2")  # half: 1 s
    seen = []

    async def scenario(page):
        await offline(page)
        await page.route("https://www.carrefour.fr/", html(fixtures.HOME_PAGE))
        pages = {1: fixtures.CARREFOUR_SEARCH_PAGE1, 2: fixtures.CARREFOUR_SEARCH_PAGE2}
        await page.route(re.compile(r"https://www\.carrefour\.fr/s\?q=.*"), json_pages(pages, seen, delay=1.2))
        return await SCRAPERS["carrefour"].search(page, "farine", None)

    products = run_scenario(manager, "carrefour-slow", scenario)
    assert len(products) == 2
    assert len(seen) == 1  # page 2 never asked


def test_lidl_reads_the_next_products(manager):
    seen = []

    async def scenario(page):
        await offline(page)
        await page.route("https://www.lidl.fr/", html(fixtures.HOME_PAGE))
        pages = {0: fixtures.LIDL_SEARCH_PAGE1, 2: fixtures.LIDL_SEARCH_PAGE2}
        await page.route(re.compile(r"https://www\.lidl\.fr/q/api/search.*"), json_pages(pages, seen))
        return await SCRAPERS["lidl"].search(page, "farine", None)

    products = run_scenario(manager, "lidl-pages", scenario)
    assert [p.name for p in products] == ["Farine de blé T55", "Farine de seigle", "Farine de blé complète"]
    assert "offset=2" in seen[1] and "fetchsize=48" in seen[0]
    assert len(seen) == 2


def test_aldi_follows_voir_plus(manager):
    async def scenario(page):
        await offline(page)
        await page.route(re.compile(r"https://www\.aldi\.fr/recherche\.html.*"), html(fixtures.ALDI_PAGE_MORE))
        return await SCRAPERS["aldi"].search(page, "farine", None)

    products = run_scenario(manager, "aldi-more", scenario)
    assert [p.name for p in products] == ["Farine de blé T55", "Farine de sarrasin", "Farine de seigle"]
    assert [p.sku for p in products] == ["1001", "1002", "1003"]
    assert SCRAPERS["aldi"].last_source == "html"


def test_aldi_follows_the_link_to_page_2(manager):
    seen = []

    async def scenario(page):
        await offline(page)

        async def search(route, request):
            seen.append(request.url)
            body = fixtures.ALDI_PAGE_2_OF_2 if "page=2" in request.url else fixtures.ALDI_PAGE_1_OF_2
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)

        await page.route(re.compile(r"https://www\.aldi\.fr/recherche\.html.*"), search)
        return await SCRAPERS["aldi"].search(page, "farine", None)

    products = run_scenario(manager, "aldi-next", scenario)
    assert [p.name for p in products] == ["Farine de blé T55", "Farine complète"]
    assert len(seen) == 2


def test_aldi_single_page_is_unchanged(manager):
    async def scenario(page):
        await offline(page)
        await page.route(re.compile(r"https://www\.aldi\.fr/recherche\.html.*"), html(fixtures.ALDI_PAGE))
        return await SCRAPERS["aldi"].search(page, "farine", None)

    assert len(run_scenario(manager, "aldi-one", scenario)) == 3


def test_json_ld_page_gives_the_barcode(manager):
    async def scenario(page):
        await offline(page)
        await page.route("https://shop.example/p/huile", html(fixtures.JSON_LD_PAGE))
        await page.goto("https://shop.example/p/huile")
        return await extract.extract_json_ld(page, "x", "https://shop.example")

    (product,) = run_scenario(manager, "json-ld", scenario)
    assert product.ean == "3265478901236"
