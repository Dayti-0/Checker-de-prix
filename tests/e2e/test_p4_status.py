"""B55, B56: page « État des enseignes » (#/etat) and the home card of the state of the retailers."""

import re

from playwright.sync_api import expect

from backend import config
from tests.e2e.axe import assert_accessible

# Width beyond the screen: on a phone the layout viewport grows with the page,
# so the visible width is the reference (not innerWidth)
OVERFLOW = "() => document.documentElement.scrollWidth - Math.round(window.visualViewport.width)"


def choose_coursesu_store(page):
    url = "https://www.coursesu.com/drive-superu-roujan"
    assert page.request.put(f"{page.base}/api/retailers/coursesu/store", data={"url": url}).ok


def search(page, query):
    """A search at every retailer, through the API (written to the journal)."""
    assert page.request.get(f"{page.base}/api/search", params={"q": query}).ok


def test_status_page(desktop):
    page = desktop
    page.goto(page.base)
    choose_coursesu_store(page)
    for query in ("farine", "huile", "eau"):
        search(page, query)
    config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (config.DEBUG_DIR / "coursesu.html").write_text("<html><body>Vérification</body></html>", encoding="utf-8")
    try:
        page.goto(f"{page.base}/#/etat")
        expect(page).to_have_title("État des enseignes · PrixMalin")
        cards = page.locator(".status-card")
        expect(cards).to_have_count(6)

        aldi = page.locator(".status-card[data-retailer=aldi]")
        expect(aldi).to_contain_text("Prêt")
        expect(aldi).to_contain_text("Prix identiques partout en France")
        expect(aldi).to_contain_text("Réussite sur 7 jours")

        intermarche = page.locator(".status-card[data-retailer=intermarche]")
        expect(intermarche).to_contain_text("Magasin à choisir")
        expect(intermarche.get_by_role("link", name="Choisir mon magasin Intermarché")).to_have_attribute(
            "href", "#/reglages?enseigne=intermarche"
        )

        coursesu = page.locator(".status-card[data-retailer=coursesu]")
        expect(coursesu).to_contain_text("Vérification requise")
        expect(coursesu).to_contain_text("Dernière erreur")
        expect(coursesu.get_by_role("button", name="Faire la vérification sur le site Courses U")).to_be_visible()
        capture = coursesu.get_by_role("link", name=re.compile("^Voir la capture Courses U"))
        expect(capture).to_have_attribute("href", "/api/status/snapshot/coursesu.html")
        assert page.request.get(f"{page.base}/api/status/snapshot/coursesu.html").ok
        assert_accessible(page, "état des enseignes")

        # « Tester »: a search read again on the site, its result and its duration
        aldi.get_by_role("button", name="Tester Aldi").click()
        expect(aldi).to_contain_text(re.compile(r"Test « farine » : 2 produits trouvés en \d+ ms"))
        expect(aldi.get_by_role("button", name="Tester Aldi")).to_be_enabled()
        coursesu.get_by_role("button", name="Tester Courses U").click()
        expect(coursesu).to_contain_text("Test « farine » : Courses U affiche une vérification anti-robot")

        # The diagnostic report
        link = page.get_by_role("link", name="Télécharger le diagnostic")
        expect(link).to_have_attribute("href", "/api/status/diagnostic.zip")
        response = page.request.get(f"{page.base}/api/status/diagnostic.zip")
        assert response.ok and response.headers["content-type"] == "application/zip"
        with page.expect_download() as download:
            link.click()
        assert download.value.suggested_filename.startswith("prixmalin-diagnostic-")
    finally:
        (config.DEBUG_DIR / "coursesu.html").unlink(missing_ok=True)


def test_status_page_in_dark_mode_and_on_a_phone(dark, mobile):
    for page in (dark, mobile):
        page.goto(page.base)
        search(page, "farine")
        page.goto(f"{page.base}/#/etat")
        expect(page.locator(".status-card")).to_have_count(6)
        assert_accessible(page, "état des enseignes")
        overflow = page.evaluate(OVERFLOW)
        assert overflow <= 0


def test_fix_from_the_status_page(desktop):
    page = desktop
    page.goto(page.base)
    choose_coursesu_store(page)
    search(page, "farine")
    page.goto(f"{page.base}/#/etat")
    coursesu = page.locator(".status-card[data-retailer=coursesu]")
    coursesu.get_by_role("button", name="Faire la vérification sur le site Courses U").click()
    expect(page.locator("#setup-banner")).to_be_visible()
    page.get_by_role("button", name="J'ai terminé").click()
    expect(page.locator("#setup-banner")).to_be_hidden()
    coursesu.get_by_role("button", name="Tester Courses U").click()
    expect(coursesu).to_contain_text("Test « farine » : 1 produit trouvé")
    expect(coursesu.locator(".pill")).to_have_text("Prêt")


def test_store_unknown_to_the_site_leads_to_another_store(desktop, monkeypatch):
    """« Ce magasin n'existe plus » (404 on the page of the store): État and Réglages say so and lead to the list."""
    from backend.scrapers.base import StoreRequiredError
    from backend.scrapers.coursesu import STORE_GONE
    from backend.services import search as search_service

    fake_scrape = search_service._scrape

    async def gone(scraper, query, store):
        if scraper.key == "coursesu" and store and store.url.endswith("roujan"):
            raise StoreRequiredError(STORE_GONE)
        return await fake_scrape(scraper, query, store)

    monkeypatch.setattr(search_service, "_scrape", gone)
    page = desktop
    page.goto(page.base)
    page.request.post(f"{page.base}/api/settings/location", data={"postal_code": "34480"})
    choose_coursesu_store(page)
    result = page.request.get(f"{page.base}/api/search/coursesu", params={"q": "farine"}).json()
    assert (result["status"], result["message"]) == ("store_required", STORE_GONE)

    page.goto(f"{page.base}/#/etat")
    card = page.locator(".status-card[data-retailer=coursesu]")
    expect(card.locator(".pill")).to_have_text("Magasin à choisir")
    expect(card).to_contain_text("Le site ne reconnaît plus le magasin choisi")
    expect(card.locator(".status-error")).to_contain_text(STORE_GONE)
    assert_accessible(page, "état, magasin inconnu du site")
    card.get_by_role("link", name="Choisir un autre magasin Courses U").click()

    expect(page).to_have_url(re.compile(r"#/reglages\?enseigne=coursesu$"))
    row = page.locator(".retailer-row[data-retailer=coursesu]")
    expect(row.locator(".pill")).to_have_text("Magasin à changer")
    expect(row).to_contain_text(STORE_GONE)
    # The list of the nearest stores opens by itself
    options = row.locator(".store-option")
    expect(options).to_have_count(8)
    assert_accessible(page, "réglages, magasin inconnu du site")
    options.filter(has_text="Super U Pézenas").click()
    expect(row).to_contain_text("✓ Super U Pézenas")
    expect(row.locator(".pill")).to_have_text("Prêt")
    expect(row).not_to_contain_text(STORE_GONE)
    page.wait_for_timeout(300)
    expect(options).to_have_count(0)  # closed after the choice, not opened again
    states = {h["key"]: h for h in page.request.get(f"{page.base}/api/status/retailers").json()}
    assert states["coursesu"]["state"] != "store_required"


def test_home_card_of_the_state(desktop):
    page = desktop
    page.goto(page.base)
    expect(page.locator(".home-status")).to_have_count(0)  # nothing before the first search
    choose_coursesu_store(page)
    for query in ("farine", "huile", "eau"):
        search(page, query)
    page.reload()
    card = page.locator(".home-status")
    expect(card).to_contain_text("Courses U demande une vérification anti-robot depuis 3 recherches.")
    expect(card.locator(".pill")).to_have_count(6)
    assert_accessible(page, "accueil avec l'état des enseignes")
    card.get_by_role("link", name="Voir l'état des enseignes").click()
    expect(page).to_have_url(re.compile(r"#/etat$"))
