"""End-to-end tests of the web interface in a real headless Chromium.

The FastAPI app runs with uvicorn in a background thread, on a free port and a
temporary data directory. Nothing leaves the machine: the search service
returns fixed products (backend.services.search._scrape is replaced), and the
geocoding and the PrixMalin browser (store finder, "Ouvrir le site") are faked.
"""

import asyncio
import socket
import threading
import time

import pytest

pytest.importorskip("playwright")

import uvicorn  # noqa: E402
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import expect, sync_playwright

from backend import config, database, main  # noqa: E402
from backend.models import Location, Product, StoreOption  # noqa: E402
from backend.services import search, settings  # noqa: E402
from backend.services import stores as stores_service  # noqa: E402
from tests.conftest import browser_missing  # noqa: E402

CATALOG = {
    "aldi": [("Farine de blé T55 1kg", 0.79, 0.79), ("Farine de sarrasin 500g", 1.49, 2.98)],
    "lidl": [("Farine de blé 1kg", 0.75, 0.75)],
    "carrefour": [("Farine T45 Carrefour 1kg", 0.85, 0.85), ("Farine fluide Francine 1kg", 1.89, 1.89)],
    "intermarche": [("Farine de blé Chabrior 1kg", 0.89, 0.89)],
    "coursesu": [("Farine de blé U 1kg", 0.95, 0.95)],
    "leclerc": [("Farine de blé Marque Repère 1kg", 0.82, 0.82)],
}
LABELS = ["Aldi", "Lidl", "Carrefour", "Intermarché", "Courses U", "E.Leclerc"]


async def fake_scrape(scraper, query, store):
    # Like the real site, Intermarché shows no price until a store is chosen
    hide_prices = scraper.key == "intermarche" and store is None
    return [
        Product(
            store=scraper.key,
            name=name,
            price=None if hide_prices else price,
            unit_price=None if hide_prices else unit_price,
            unit="kg",
            product_url=f"https://{scraper.key}.example/p/{index}",
        )
        for index, (name, price, unit_price) in enumerate(CATALOG[scraper.key])
        if query.lower() in name.lower()
    ]


async def fake_geocode(postal_code):
    return [Location(postal_code=postal_code, city="Montpellier", lat=43.61, lon=3.87)]


INTERMARCHE_STORES = [
    StoreOption(
        id="06814", name="Intermarché Hyper Lattes", address="Route de Montpellier, 34970 Lattes", distance_km=0.9
    ),
    StoreOption(id="08012", name="Intermarché Super Montpellier", distance_km=2.5),
]


async def fake_browser_run(key, fn, *args, timeout=None, priority="interactive"):
    assert fn.__name__ == "find_stores", "only the store finder goes through the browser"
    return INTERMARCHE_STORES


async def fake_coursesu_directory(department_name=None):
    # No Courses U store around (P4: tests/e2e/test_p4_stores.py tests the list)
    return {"stores": [], "method": "blocs"}


async def fake_leclerc_nearby(location):
    # No E.Leclerc drive around (P8: tests/e2e/test_p8_leclerc.py tests the list)
    return []


async def fake_open_setup(key, url):
    main.browser.setup_mode = True


async def fake_end_setup():
    main.browser.setup_mode = False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def temp_data_dir():
    """The server of this module keeps its own data directory (see `server`)."""
    yield


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("e2e-data")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PRIXMALIN_WARMUP", "0")
        mp.setattr(config, "DATA_DIR", data_dir)
        mp.setattr(config, "DB_PATH", data_dir / "e2e.db")
        mp.setattr(config, "DEBUG_DIR", data_dir / "debug")
        mp.setattr(search, "_scrape", fake_scrape)
        mp.setattr(settings, "geocode", fake_geocode)
        mp.setattr(main.browser, "run", fake_browser_run)
        mp.setattr(stores_service, "fetch_coursesu_directory", fake_coursesu_directory)
        mp.setattr(stores_service, "fetch_leclerc_nearby", fake_leclerc_nearby)
        mp.setattr(main.browser, "open_setup", fake_open_setup)
        mp.setattr(main.browser, "end_setup", fake_end_setup)
        database._db = None
        port = free_port()
        uv = uvicorn.Server(
            uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=5)
        )
        thread = threading.Thread(target=uv.run, name="e2e-uvicorn", daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not uv.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                pytest.fail("Le serveur PrixMalin n'a pas démarré")
            time.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
        uv.should_exit = True
        thread.join(timeout=15)
        if thread.is_alive():
            uv.force_exit = True
            thread.join(timeout=5)
        # An aiosqlite connection left open would keep the interpreter alive at exit
        asyncio.run(database.close_db())


@pytest.fixture(scope="module")
def chromium():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(timeout=60000)
        except PlaywrightError as e:
            browser_missing(f"Chromium unavailable: {e}")
        yield browser
        browser.close()


@pytest.fixture
def page(server, chromium):
    context = chromium.new_context(viewport={"width": 1280, "height": 900}, locale="fr-FR")
    page = context.new_page()
    page.set_default_timeout(10000)
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    # Each test starts with an empty list and no store chosen
    for path in ("/api/list", "/api/retailers/intermarche/store", "/api/retailers/coursesu/store"):
        assert page.request.delete(server + path).ok
    page.base = server
    yield page
    context.close()
    assert errors == []


def search_farine(page):
    page.fill("#q", "farine")
    page.press("#q", "Enter")
    expect(page).to_have_url(f"{page.base}/#/recherche?q=farine")
    columns = page.locator(".column")
    expect(columns).to_have_count(6)
    for i in range(6):
        expect(columns.nth(i).locator(".product").first).to_be_visible()
    expect(page.locator(".summary-progress")).to_have_count(0)  # every retailer answered


def test_home_renders(page):
    page.goto(page.base)
    expect(page).to_have_url(f"{page.base}/#/")
    expect(page).to_have_title("Rechercher · PrixMalin")
    expect(page.locator("#q")).to_be_visible()
    expect(page.locator(".welcome")).to_contain_text("Tapez un produit")
    expect(page.locator(".store-toggle")).to_have_count(6)
    expect(page.locator("#primary-nav .nav-link")).to_have_text(["Rechercher", "Ma liste 0", "Réglages"])
    expect(page.locator("#primary-nav .nav-link.active")).to_have_text("Rechercher")
    expect(page.locator("#location-label")).not_to_be_empty()  # "Code postal" or the saved location


def test_search_shows_one_column_per_retailer(page):
    page.goto(page.base)
    search_farine(page)
    expect(page.locator(".column-head .badge")).to_have_text(LABELS)
    expect(page.locator(".column[data-store=aldi] .price")).to_have_text(["0,79 €", "1,49 €"])
    expect(page.locator(".column[data-store=lidl] .price")).to_have_text(["0,75 €"])
    expect(page.locator(".column[data-store=lidl] .product.best")).to_contain_text("Le moins cher")
    expect(page.locator(".summary-card").first).to_contain_text("0,75 €")
    expect(page).to_have_title("farine – Rechercher · PrixMalin")

    # Sort by unit price, then the store filter hides a column
    page.get_by_role("radio", name="Prix au kg").check()
    expect(page.locator(".column[data-store=aldi] .unit")).to_have_text(["0,79 €/kg", "2,98 €/kg"])
    page.locator(".store-toggle", has_text="Carrefour").click()
    expect(page.locator(".column")).to_have_count(5)
    page.locator(".store-toggle", has_text="Carrefour").click()
    expect(page.locator(".column")).to_have_count(6)


def test_store_required_leads_to_the_settings(page):
    page.goto(page.base)
    search_farine(page)
    column = page.locator(".column[data-store=intermarche]")
    expect(column.locator(".column-status")).to_have_text("Magasin à choisir")
    expect(column.locator(".price")).to_have_text(["Prix non affiché"])

    column.locator("[data-open-settings]").click()
    expect(page).to_have_url(f"{page.base}/#/reglages?enseigne=intermarche")
    page.fill("#location-postal", "34970")
    page.press("#location-postal", "Enter")
    expect(page.locator("#location-label")).to_have_text("34970 Montpellier")
    # The list of the retailer of the address opens by itself (B52)
    options = page.locator("[data-retailer=intermarche] .store-option")
    expect(options).to_have_count(2)
    expect(options.first).to_contain_text("Intermarché Hyper Lattes")
    expect(options.first).to_contain_text("≈ 1 km")
    options.first.click()
    expect(page.locator("#toast")).to_have_text("Magasin Intermarché : Intermarché Hyper Lattes")
    card = page.locator("[data-retailer=intermarche]")
    expect(card.locator(".retailer-detail")).to_have_text("✓ Intermarché Hyper Lattes · ≈ 1 km")
    expect(card).to_contain_text("Route de Montpellier, 34970 Lattes")

    # The search was run again in the background with the chosen store
    page.click(".nav-link[data-nav=search]")
    expect(page).to_have_url(f"{page.base}/#/recherche?q=farine")
    expect(column.locator(".price")).to_have_text(["0,89 €"])
    expect(column.locator(".column-sub")).to_have_text("Intermarché Hyper Lattes")

    page.goto(f"{page.base}/#/reglages")
    page.get_by_role("button", name="Autres actions pour Intermarché").click()
    page.get_by_role("button", name="Retirer le magasin Intermarché").click()
    expect(page.locator("#toast")).to_have_text("Magasin Intermarché retiré")
    expect(card.locator(".pill")).to_have_text("Magasin à choisir")


def test_add_to_list_updates_the_nav_badge(page):
    page.goto(page.base)
    search_farine(page)
    expect(page.locator(".nav-link[data-nav=list] .count")).to_have_text("0")
    page.locator(".column[data-store=lidl] .add-btn").first.click()
    page.click("#add-sheet button[type=submit]")  # « Ajouter », exactly this product
    expect(page.locator("#toast")).to_contain_text("Ajouté à « farine »")
    expect(page.locator(".nav-link[data-nav=list] .count")).to_have_text("1")
    # The search only, at another retailer: same query, merged into the same line
    page.locator(".column[data-store=aldi] .add-btn").first.click()
    page.check("#add-sheet input[value=query]")
    page.click("#add-sheet button[type=submit]")
    expect(page.locator("#toast")).to_contain_text("« farine »")
    expect(page.locator(".nav-link[data-nav=list] .count")).to_have_text("1")


def test_list_compares_the_basket(page):
    page.goto(page.base)
    search_farine(page)
    page.locator(".column[data-store=carrefour] .add-btn").nth(1).click()  # Francine at Carrefour
    page.click("#add-sheet button[type=submit]")
    expect(page.locator(".nav-link[data-nav=list] .count")).to_have_text("1")

    page.click(".nav-link[data-nav=list]")
    expect(page).to_have_url(f"{page.base}/#/liste")
    expect(page.locator(".list-row")).to_have_count(1)
    expect(page.locator(".row-pick")).to_contain_text("Carrefour · Farine fluide Francine 1kg")

    page.fill("#list-input", "farine de blé")
    page.fill("#list-qty", "2")
    page.click("#list-form button[type=submit]")
    expect(page.locator(".list-row")).to_have_count(2)
    expect(page.locator(".nav-link[data-nav=list] .count")).to_have_text("2")

    # Courses U unticked here, then searched without it, then ticked again here:
    # back in the search, its column must have been searched
    page.locator(".store-toggle", has_text="Courses U").click()
    page.click(".nav-link[data-nav=search]")
    page.click("#refresh-btn")
    expect(page.locator(".column")).to_have_count(5)
    expect(page.locator(".summary-progress")).to_have_count(0)
    page.click(".nav-link[data-nav=list]")
    page.locator(".store-toggle", has_text="Courses U").click()

    # P5: the comparison has its own page (#/panier)
    page.get_by_role("button", name="Comparer mon panier").click()
    expect(page).to_have_url(f"{page.base}/#/panier")
    expect(page.locator(".store-card")).to_have_count(6)
    verdict = page.get_by_test_id("basket-verdict")
    expect(verdict).to_contain_text("Panier le moins cher")
    expect(verdict.locator(".badge")).to_have_text("Lidl")
    expect(verdict).to_contain_text("2,25 €")  # 0,75 + 2 × 0,75
    expect(page.locator(".store-card.best .badge")).to_have_text("Lidl")
    expect(page.locator(".basket-table tbody tr")).to_have_count(2)

    # The results and the comparison survive a trip between the views
    page.click(".nav-link[data-nav=search]")
    expect(page).to_have_url(f"{page.base}/#/recherche?q=farine")
    expect(page.locator(".column")).to_have_count(6)
    expect(page.locator(".column[data-store=coursesu] .price")).to_have_text(["0,95 €"])
    page.go_back()
    expect(page).to_have_url(f"{page.base}/#/panier")
    expect(page.locator(".store-card")).to_have_count(6)
    expect(page.get_by_test_id("basket-verdict")).to_contain_text("2,25 €")


def test_settings_page(page):
    page.goto(f"{page.base}/#/reglages")
    expect(page).to_have_title("Réglages · PrixMalin")
    expect(page.locator(".retailer-row")).to_have_count(6)
    expect(page.locator(".retailer-row .badge")).to_have_text(LABELS)
    expect(page.locator("[data-retailer=intermarche] .pill")).to_have_text("Magasin à choisir")
    expect(page.locator("#browser-status")).to_have_text("Le navigateur démarrera à la première recherche.")

    page.fill("#location-postal", "34000")
    page.press("#location-postal", "Enter")
    expect(page.locator("#toast")).to_have_text("Localisation enregistrée : Montpellier")
    expect(page.locator("#location-label")).to_have_text("34000 Montpellier")
    expect(page.locator("#location-info")).to_have_text("Localisation : Montpellier")

    coursesu = page.locator("[data-retailer=coursesu]")
    coursesu.get_by_role("button", name="Choisir mon magasin Courses U").click()
    coursesu.get_by_text("Saisir l'adresse à la main").click()
    coursesu.locator("#coursesu-url").fill("https://www.coursesu.com/drive-superu-roujan")
    coursesu.get_by_role("button", name="Enregistrer").click()
    expect(page.locator("#toast")).to_have_text("Magasin Courses U : Super U Roujan")
    expect(coursesu.locator(".retailer-detail")).to_have_text("✓ Super U Roujan")
    page.get_by_role("button", name="Autres actions pour Courses U").click()
    page.get_by_role("button", name="Retirer le magasin Courses U").click()
    expect(coursesu.locator(".pill")).to_have_text("Magasin à choisir")

    # "Ouvrir le site" shows the banner of the shell until "J'ai terminé"
    expect(page.locator("#setup-banner")).to_be_hidden()
    page.get_by_role("button", name="Autres actions pour Aldi").click()
    page.get_by_role("button", name="Ouvrir le site Aldi").click()
    expect(page.locator("#toast")).to_contain_text("Aldi est ouvert dans la fenêtre du navigateur PrixMalin")
    expect(page.locator("#setup-banner")).to_be_visible()
    page.click("#setup-banner-done")
    expect(page.locator("#toast")).to_have_text("C'est noté, les recherches reprennent en arrière-plan")
    expect(page.locator("#setup-banner")).to_be_hidden()

    # The settings button and the location chip lead here
    page.click(".brand")
    expect(page).to_have_url(f"{page.base}/#/")
    page.click("#settings-btn")
    expect(page.locator(".settings-page")).to_be_visible()


def test_text_size_buttons(page):
    page.goto(page.base)
    font_size = "() => parseFloat(getComputedStyle(document.documentElement).fontSize)"
    before = page.evaluate(font_size)
    page.click("#text-bigger")
    after = page.evaluate(font_size)
    assert after > before
    assert page.evaluate("localStorage.getItem('prixmalin.textScale')") is not None
    page.reload()
    assert page.evaluate(font_size) == after
    page.click("#text-smaller")
    assert page.evaluate(font_size) == before


def test_old_search_links_redirect(page):
    page.goto(f"{page.base}/?q=farine")
    expect(page).to_have_url(f"{page.base}/#/recherche?q=farine")
    expect(page.locator("#q")).to_have_value("farine")
    expect(page.locator(".column")).to_have_count(6)
    expect(page.locator(".column[data-store=lidl] .price")).to_have_text(["0,75 €"])


def test_unknown_route_goes_to_search(page):
    page.goto(f"{page.base}/#/inconnu")
    expect(page).to_have_url(f"{page.base}/#/")
    expect(page.locator("#q")).to_be_visible()
