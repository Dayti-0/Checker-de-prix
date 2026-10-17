"""« Mon panier » (#/panier): live comparison (B59), honest verdict (B57), « Changer » (B60),
plans (B61), readable on a phone and on a computer (B62), prices seen in the store (B71).

Products: tests/e2e/catalog_p5.py (« beurre, sucre, lessive, jus d'orange (6 L) »):
Carrefour has everything (17,39 €); Aldi has no washing liquid (15,12 € estimated), Lidl
no orange juice (7,77 € found, 15,57 € estimated); Intermarché asks for a store, Courses U
for its anti-robot check.
"""

import asyncio
import re
import threading

import pytest
from playwright.sync_api import expect

from backend.browser import browser
from backend.services import search
from tests.e2e import fake
from tests.e2e.axe import assert_accessible
from tests.e2e.catalog_p5 import add, call, compare, demo_list, horizontal_overflow, pdf_pages


class Gate:
    """The searches of the retailers in ``held`` wait until ``release()``."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.held: set[str] = set()

    def release(self) -> None:
        self.event.set()


@pytest.fixture
def gate(monkeypatch):
    g = Gate()

    async def gated(scraper, query, store):
        if scraper.key in g.held:
            while not g.event.is_set():  # noqa: ASYNC110 (set from the thread of the test)
                await asyncio.sleep(0.02)
        return await fake.fake_scrape(scraper, query, store)

    monkeypatch.setattr(search, "_scrape", gated)
    yield g
    g.release()


def card(page, key):
    return page.locator(f"[data-store-card={key}]")


def cell(page, key, query):
    item = next(i for i in call(page, "GET", "/api/list") if i["query"] == query)
    return page.locator(f'[data-cell="{key}:{item["id"]}"]')


def open_basket(page):
    page.goto(f"{page.base}/#/panier")
    expect(page.get_by_test_id("basket-verdict")).to_be_visible()


def test_live_comparison_then_an_honest_verdict(desktop, gate):
    page = desktop
    demo_list(page)
    gate.held = {"lidl"}
    page.goto(f"{page.base}/#/liste")
    page.get_by_role("button", name="Comparer mon panier").click()
    expect(page).to_have_url(re.compile(r"#/panier$"))

    # While Lidl is searched: progress, « Arrêter », the cells already read
    progress = page.get_by_test_id("basket-progress")
    expect(progress).to_contain_text(re.compile(r"Comparaison en cours : \d+/20 recherches"))
    expect(page.get_by_role("button", name="Arrêter")).to_be_visible()
    expect(card(page, "aldi")).to_contain_text("Tous les articles sont lus")
    expect(cell(page, "aldi", "beurre")).to_contain_text("1,89 €")
    expect(cell(page, "lidl", "beurre").get_by_text("En attente")).to_have_count(1)
    expect(page.get_by_test_id("basket-verdict")).to_contain_text("Comparaison en cours")
    expect(page.get_by_text("Panier le moins cher")).to_have_count(0)
    assert_accessible(page, "panier en cours")

    gate.release()
    verdict = page.get_by_test_id("basket-verdict")
    expect(verdict).to_contain_text("Panier le moins cher")
    expect(verdict).to_contain_text("Carrefour")
    expect(verdict).to_contain_text("17,39 €")
    expect(verdict).to_contain_text("Panier complet : 4/4 articles")
    expect(page.get_by_role("button", name="Actualiser les prix")).to_be_visible()
    expect(page.locator("#live-region")).to_contain_text("Comparaison terminée")

    # Ranked by complete basket, then estimated total: Lidl (cheaper on what it has) after Aldi
    order = page.locator("[data-store-card]").evaluate_all("(cards) => cards.map((c) => c.dataset.storeCard)")
    assert order == ["carrefour", "aldi", "lidl", "intermarche", "coursesu"]
    expect(card(page, "aldi")).to_contain_text("2e")
    expect(card(page, "aldi")).to_contain_text("Total estimé15,12 €")
    expect(card(page, "lidl")).to_contain_text("3e")
    expect(card(page, "lidl")).to_contain_text("Articles trouvés7,77 €")
    expect(card(page, "lidl")).to_contain_text("Total estimé15,57 €")
    expect(card(page, "lidl")).to_contain_text("1 article introuvable")
    expect(card(page, "lidl")).to_contain_text("Sur les 2 articles communs : 2,78 €")

    # Retailers that could not be searched: their reason and their action
    expect(card(page, "intermarche")).to_contain_text("Magasin à choisir")
    expect(card(page, "intermarche").get_by_role("link", name="Choisir mon magasin Intermarché")).to_have_attribute(
        "href", "#/reglages?enseigne=intermarche"
    )
    expect(card(page, "coursesu")).to_contain_text("Vérification requise")
    expect(card(page, "coursesu").get_by_role("button", name="Ouvrir le site Courses U")).to_be_visible()

    expect(cell(page, "lidl", "jus d'orange")).to_contain_text("Introuvable")
    expect(cell(page, "lidl", "jus d'orange")).to_contain_text("compté 7,80 € dans l'estimation")
    expect(cell(page, "aldi", "jus d'orange")).to_contain_text("6,90 €")  # 6 x 1 L for 6 L
    expect(cell(page, "carrefour", "jus d'orange")).to_contain_text("6 × 1,45 €")
    plans = page.get_by_test_id("plans")
    expect(plans).to_contain_text("Tout chez Carrefour")
    expect(plans.get_by_role("link", name="Suivre le plan Tout chez Carrefour")).to_have_attribute(
        "href", "#/courses?plan=0"
    )
    assert_accessible(page, "panier")

    # « Actualiser les prix » reads the sites again
    with page.expect_request(re.compile(r"/api/basket/compare/stream\?.*refresh=true")):
        page.get_by_role("button", name="Actualiser les prix").click()
    expect(page.get_by_test_id("basket-verdict")).to_contain_text("Panier le moins cher")


def test_stop_then_resume(desktop, gate):
    page = desktop
    demo_list(page)
    gate.held = set(fake.CATALOG)
    page.goto(f"{page.base}/#/panier")  # no comparison yet: it starts by itself
    expect(page.get_by_test_id("basket-progress")).to_be_visible()
    page.get_by_role("button", name="Arrêter").click()
    expect(page.get_by_text(re.compile(r"Comparaison arrêtée : \d+/20 recherches faites\."))).to_be_visible()
    expect(page.locator("#live-region")).to_have_text("Comparaison arrêtée")
    expect(page.get_by_role("button", name="Arrêter")).to_have_count(0)
    gate.release()
    page.get_by_role("button", name="Reprendre").click()
    expect(page.get_by_test_id("basket-verdict")).to_contain_text("Panier le moins cher")


def test_no_complete_basket_is_never_called_the_cheapest(mobile):
    page = mobile
    demo_list(page)
    add(page, "gâteau")  # only at Aldi: nobody has everything
    page.goto(f"{page.base}/#/panier")
    verdict = page.get_by_test_id("basket-verdict")
    expect(verdict).to_contain_text("Aucune enseigne n'a tout : Aldi en a le plus (4/5)")
    expect(verdict).to_contain_text("17,31 €")
    expect(verdict).to_contain_text("estimé")
    expect(verdict).to_contain_text("Total estimé : les articles introuvables sont comptés au prix médian")
    expect(page.get_by_text("Panier le moins cher")).to_have_count(0)
    # Lidl, 2 items missing, cheaper on what it has, is not shown as cheaper than Aldi
    expect(card(page, "aldi")).to_contain_text("1er")
    expect(card(page, "lidl")).to_contain_text("2e")
    expect(card(page, "lidl")).to_contain_text("2 articles introuvables")
    expect(card(page, "lidl")).to_contain_text("17,76 €")
    expect(page.get_by_test_id("plans")).to_contain_text("Lidl + Aldi")
    assert horizontal_overflow(page) == 0


def test_change_the_product_then_back_to_the_automatic_choice(desktop):
    page = desktop
    demo_list(page)
    compare(page)
    open_basket(page)
    page.get_by_role("button", name="Changer le produit jus d'orange chez Aldi").click()
    sheet = page.get_by_role("dialog", name="« jus d'orange » chez Aldi")
    current = sheet.get_by_role("button", name=re.compile(r"^Choisir Jus d'orange 6x1L"))
    expect(current).to_have_attribute("aria-current", "true")
    expect(current).to_contain_text("Retenu")
    assert_accessible(page, "feuille « Changer »")
    sheet.get_by_role("button", name="Choisir Jus d'orange Rio D'oro (Aldi, 1,29 €)").click()
    expect(sheet).to_be_hidden()
    expect(page.get_by_role("status")).to_contain_text("Jus d'orange retenu chez Aldi")

    juice = cell(page, "aldi", "jus d'orange")
    expect(juice).to_contain_text("7,74 €")  # 6 x 1,29 € for the 6 L
    expect(juice).to_contain_text("votre choix")
    expect(page.locator("tfoot")).to_contain_text("10,72 €")
    expect(page.get_by_role("button", name="Changer le produit jus d'orange chez Aldi")).to_be_focused()
    page.reload()
    expect(cell(page, "aldi", "jus d'orange")).to_contain_text("7,74 €")

    page.get_by_role("button", name="Changer le produit jus d'orange chez Aldi").click()
    page.get_by_role("dialog").get_by_role("button", name="Revenir au choix automatique").click()
    expect(page.get_by_role("status")).to_contain_text("Aldi : retour au choix automatique")
    expect(cell(page, "aldi", "jus d'orange")).to_contain_text("6,90 €")
    assert next(i for i in call(page, "GET", "/api/list") if i["query"] == "jus d'orange")["picks"] == {}


def test_not_available_here(desktop):
    page = desktop
    demo_list(page)
    compare(page)
    open_basket(page)
    page.get_by_role("button", name="Changer le produit beurre chez Lidl").click()
    page.get_by_role("dialog").get_by_role("button", name="Pas disponible chez Lidl").click()
    expect(page.get_by_role("status")).to_contain_text("« beurre » : pas disponible chez Lidl")
    expect(cell(page, "lidl", "beurre")).to_contain_text("Pas disponible ici")
    lidl = card(page, "lidl")
    expect(lidl).to_contain_text("1 article pas disponible ici")
    expect(lidl).to_contain_text("1 article introuvable")  # the juice; the butter is not missing
    beurre = next(i for i in call(page, "GET", "/api/list") if i["query"] == "beurre")
    assert beurre["excluded"] == ["lidl"]

    page.get_by_role("button", name="Changer le produit beurre chez Lidl").click()
    page.get_by_role("dialog").get_by_role("button", name="Comparer de nouveau chez Lidl").click()
    expect(cell(page, "lidl", "beurre")).to_contain_text("1,79 €")


def test_type_a_price_seen_in_the_store(mobile):
    page = mobile
    demo_list(page)
    compare(page)
    open_basket(page)
    page.get_by_role("button", name="Saisir le prix de lessive chez Aldi").click()
    sheet = page.get_by_role("dialog", name="« lessive » chez Aldi")
    expect(sheet.get_by_role("textbox", name="Prix (€)")).to_be_focused()
    sheet.get_by_role("textbox", name="Prix (€)").fill("trois euros")
    sheet.get_by_role("button", name="Enregistrer le prix").click()
    expect(sheet.get_by_role("alert")).to_have_text("Indiquez un prix, par exemple 1,49.")
    assert_accessible(page, "prix vu en magasin")
    sheet.get_by_role("textbox", name="Prix (€)").fill("4,79")
    sheet.get_by_role("textbox", name="Contenance").fill("2 L")
    sheet.get_by_role("button", name="Enregistrer le prix").click()
    expect(page.get_by_role("status")).to_contain_text("Prix saisi : 4,79 € chez Aldi")

    # Counted, with its flag: Aldi has everything now, and is the cheapest
    offer = page.locator("[data-item-card]").filter(has_text="lessive").locator("[data-offer=aldi]")
    expect(offer).to_contain_text("4,79 €")
    expect(offer).to_contain_text(re.compile(r"saisi le \d\d/\d\d"))
    expect(offer).to_contain_text(re.compile(r"à mettre à jour avant le \d\d/\d\d"))
    verdict = page.get_by_test_id("basket-verdict")
    expect(verdict).to_contain_text("Panier le moins cher")
    expect(verdict).to_contain_text("Aldi")
    expect(verdict).to_contain_text("14,67 €")
    expect(card(page, "aldi")).to_contain_text("1 prix saisi")


def test_retailers_that_could_not_be_searched(desktop, monkeypatch):
    page = desktop

    async def end_setup():
        # Like the real browser: « J'ai terminé » ends the setup of the retailer shown,
        # whose results and circuit breaker are then reset (api/browser.py)
        shown = next((k for k in reversed(fake.state.opened) if k), None)
        await fake.fake_end_setup()
        return shown

    monkeypatch.setattr(browser, "end_setup", end_setup)
    demo_list(page)
    compare(page)
    open_basket(page)
    card(page, "coursesu").get_by_role("button", name="Ouvrir le site Courses U").click()
    banner = page.locator("#setup-banner")
    expect(banner).to_be_visible()
    banner.get_by_role("button", name="J'ai terminé").click()
    # Checked by the user: Courses U is searched again, and has only the butter
    courses_u = card(page, "coursesu")
    expect(courses_u).to_contain_text("1/4 articles")
    expect(courses_u).to_contain_text("Pas classée : moins de la moitié des articles trouvés.")
    card(page, "intermarche").get_by_role("link", name="Choisir mon magasin Intermarché").click()
    expect(page).to_have_url(re.compile(r"#/reglages\?enseigne=intermarche$"))


def test_on_a_phone_one_card_per_item(mobile):
    page = mobile
    demo_list(page)
    compare(page)
    open_basket(page)
    expect(page.get_by_test_id("basket-table")).to_be_hidden()
    beurre = page.locator("[data-item-card]").filter(has=page.get_by_role("heading", name="beurre"))
    stores = beurre.locator("[data-offer]").evaluate_all("(offers) => offers.map((o) => o.dataset.offer)")
    assert stores == ["lidl", "aldi", "carrefour"]  # cheapest first; not searched: said once
    expect(beurre.locator("[data-offer=lidl]")).to_contain_text("(le moins cher)")
    expect(
        page.get_by_text("Intermarché et Courses U ne sont pas comparées : voir leur carte plus haut.")
    ).to_be_visible()
    assert_accessible(page, "panier sur téléphone")
    for width in (390, 360):
        page.set_viewport_size({"width": width, "height": 800})
        assert horizontal_overflow(page) == 0, width
    for scale in ("0.9", "1.6"):
        page.add_init_script(f"localStorage.setItem('prixmalin.textScale', '{scale}')")
        page.reload()
        expect(page.get_by_test_id("basket-verdict")).to_be_visible()
        assert horizontal_overflow(page) == 0, scale


def test_on_a_computer_a_table_in_dark_mode(dark):
    page = dark
    demo_list(page)
    compare(page)
    open_basket(page)
    table = page.get_by_role("table", name=re.compile("Prix de chaque article"))
    expect(table).to_be_visible()
    expect(page.get_by_test_id("basket-items")).to_be_hidden()
    sticky = page.locator(".basket-table thead th").first.evaluate("(th) => getComputedStyle(th).position")
    assert sticky == "sticky"
    expect(table.locator("tfoot")).to_contain_text("17,39 €")
    assert_accessible(page, "panier en sombre")


def test_second_store_when_it_is_worth_the_trip(desktop):
    page = desktop
    demo_list(page)
    compare(page)
    open_basket(page)
    plans = page.get_by_test_id("plans")
    expect(plans.locator(".plan")).to_have_count(1)
    expect(plans).to_contain_text("Un deuxième magasin n'est proposé que s'il fait économiser au moins 3,00 €.")

    page.get_by_text("Réglages du panier").click()
    saving = page.get_by_role("spinbutton", name=re.compile("Proposer un deuxième magasin"))
    expect(saving).to_have_value("3")
    saving.fill("2")
    page.get_by_role("button", name="Enregistrer les réglages").click()
    expect(page.get_by_role("status")).to_contain_text("Réglages du panier enregistrés")
    expect(plans.locator(".plan")).to_have_count(2)
    pair = plans.locator(".plan").nth(1)
    expect(pair).to_contain_text(re.compile(r"Aldi \+ Lidl|Lidl \+ Aldi"))
    expect(pair).to_contain_text("14,67 €")
    expect(pair).to_contain_text("2,72 € de moins qu'en un seul magasin")
    expect(pair.get_by_role("link", name=re.compile("^Suivre le plan"))).to_have_attribute("href", "#/courses?plan=1")


def test_the_list_changed_since_the_comparison(desktop):
    page = desktop
    demo_list(page)
    compare(page)
    add(page, "sucre", quantity=2)  # quantity changed: the totals are not right any more
    open_basket(page)
    notice = page.get_by_text("Votre liste a changé depuis cette comparaison.")
    expect(notice).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("^Changer le produit"))).to_have_count(0)
    page.get_by_role("button", name="Comparer à nouveau").click()
    expect(page.get_by_text("Votre liste a changé depuis cette comparaison.")).to_have_count(0)
    expect(cell(page, "lidl", "sucre")).to_contain_text("3 × 0,99 €")


def test_empty_list(desktop):
    page = desktop
    page.goto(f"{page.base}/#/panier")
    expect(page.get_by_role("heading", name="Votre liste est vide")).to_be_visible()
    page.get_by_role("link", name="Ajouter des articles").click()
    expect(page).to_have_url(re.compile(r"#/liste$"))


def test_printed_basket_fits_on_one_a4_page(desktop):
    page = desktop
    demo_list(page)
    compare(page)
    open_basket(page)
    page.emulate_media(media="print")
    expect(page.get_by_role("table", name=re.compile("Prix de chaque article"))).to_be_visible()
    expect(page.get_by_role("button", name="Actualiser les prix")).to_be_hidden()
    assert pdf_pages(page) == 1
