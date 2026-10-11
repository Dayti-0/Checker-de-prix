"""Recent searches and suggestions while typing (B33)."""

import re

from playwright.sync_api import expect

from tests.e2e.axe import assert_accessible
from tests.e2e.p2_helpers import search


def field(page):
    return page.get_by_role("searchbox", name="Produit à rechercher")


def options(page):
    return page.get_by_role("listbox", name="Suggestions").get_by_role("option")


def test_a_recent_search_is_suggested_and_chosen_with_the_keyboard(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "huile de tournesol")
    page.goto(f"{page.base}/#/")
    box = field(page)
    box.click()
    box.press_sequentially("hu")
    expect(options(page).first).to_contain_text("huile de tournesol")
    expect(options(page).first).to_contain_text("recherche récente")
    assert_accessible(page, "suggestions ouvertes")

    box.press("ArrowDown")
    first = options(page).first
    expect(first).to_have_attribute("aria-selected", "true")
    expect(box).to_have_attribute("aria-activedescendant", first.get_attribute("id"))
    box.press("Enter")
    expect(page).to_have_url(re.compile(r"#/recherche\?q=huile%20de%20tournesol$"))
    expect(page.get_by_role("listbox", name="Suggestions")).to_be_hidden()


def test_escape_closes_and_keeps_the_text(desktop):
    page = desktop
    page.goto(page.base)
    box = field(page)
    box.click()
    box.press_sequentially("ech")
    expect(options(page).first).to_have_text(re.compile("^Échalotes"))  # aliments.json, accents kept
    box.press("Escape")
    expect(page.get_by_role("listbox", name="Suggestions")).to_be_hidden()
    expect(box).to_have_value("ech")


def test_a_click_on_a_suggestion_searches_it(desktop):
    page = desktop
    page.goto(page.base)
    box = field(page)
    box.click()
    box.press_sequentially("vinaig")
    options(page).filter(has_text=re.compile("^Vinaigre balsamique")).click()
    expect(page).to_have_url(re.compile(r"#/recherche\?q=Vinaigre%20balsamique$"))
    expect(box).to_have_value("Vinaigre balsamique")


def test_list_lines_are_suggested(desktop):
    page = desktop
    assert page.request.post(f"{page.base}/api/list", data={"query": "pois chiches"}).ok
    page.goto(page.base)
    box = field(page)
    box.click()
    box.press_sequentially("pois")
    expect(options(page).first).to_contain_text("pois chiches")
    expect(options(page).first).to_contain_text("dans ma liste")


def test_a_recent_search_can_be_removed(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    search(page, "sucre")
    # From the suggestions: Suppr on the active option
    box = field(page)
    box.fill("")
    box.press("ArrowDown")
    expect(options(page)).to_have_count(2)
    expect(options(page).first).to_contain_text("sucre")
    box.press("Delete")
    expect(options(page)).to_have_count(1)
    expect(page.locator("#live-region")).to_have_text("« sucre » retiré des recherches récentes")

    # From the home card
    page.goto(f"{page.base}/#/")
    card = page.get_by_test_id("recent-card")
    expect(card.get_by_role("heading")).to_have_text("Recherches récentes")
    expect(card.get_by_role("button", name="farine", exact=True)).to_be_visible()
    assert_accessible(page, "recherches récentes")
    card.get_by_role("button", name="Retirer « farine » des recherches récentes").click()
    # No recent search left: the ideas of the first use
    expect(card.get_by_role("heading")).to_have_text("Idées de recherche")
    expect(card.get_by_role("button", name="Farine")).to_be_visible()
    page.reload()
    expect(page.get_by_test_id("recent-card").get_by_role("heading")).to_have_text("Idées de recherche")


def test_first_use_shows_ideas_that_search(mobile):
    page = mobile
    page.goto(page.base)
    card = page.get_by_test_id("recent-card")
    expect(card.get_by_role("button")).to_have_text(
        ["Farine", "Huile de tournesol", "Eau minérale", "Vinaigre", "Lait demi-écrémé", "Sucre"]
    )
    card.get_by_role("button", name="Vinaigre").click()
    expect(page).to_have_url(re.compile(r"#/recherche\?q=Vinaigre$"))
    expect(page.locator("#results")).to_have_attribute("aria-busy", "false")
    page.go_back()
    card = page.get_by_test_id("recent-card")
    expect(card.get_by_role("heading")).to_have_text("Recherches récentes")
    expect(card.get_by_role("button", name="Vinaigre", exact=True)).to_be_visible()


def test_screen_readers_hear_that_the_list_opens(desktop):
    from tests.e2e.helpers import js_eval

    page = desktop
    page.goto(page.base)
    module = "/static/js/views/search/autocomplete.js"
    assert js_eval(page, module, "suggestionsText", 1) == "1 suggestion, flèches haut et bas pour choisir"
    assert js_eval(page, module, "suggestionsText", 3) == "3 suggestions, flèches haut et bas pour choisir"
    assert js_eval(page, module, "suggestionsText", 0) == ""

    box = field(page)
    box.click()
    box.press_sequentially("vinaig")
    expect(options(page).first).to_be_visible()  # the list of foods may arrive after the typing
    count = options(page).count()
    live = page.locator("#live-region")
    expect(live).to_have_text(re.compile(r"^\d+ suggestions?, flèches haut et bas pour choisir$"))
    words = "suggestions" if count > 1 else "suggestion"
    expect(live).to_have_text(f"{count} {words}, flèches haut et bas pour choisir")
    # Closed then opened again: heard again
    box.press("Escape")
    page.evaluate("document.getElementById('live-region').textContent = ''")
    box.press("ArrowDown")
    expect(options(page).first).to_be_visible()
    expect(live).to_have_text(re.compile("flèches haut et bas pour choisir$"))


def test_suggestions_loaded_late_do_not_reopen_the_list(desktop):
    """On a slow machine the list of foods arrives after the search: the list stays closed."""
    page = desktop
    held = []
    page.route("**/aliments.json", lambda route: held.append(route))
    page.goto(page.base)
    box = field(page)
    box.click()
    box.press_sequentially("farine")
    box.press("Enter")
    expect(page).to_have_url(re.compile(r"#/recherche\?q=farine$"))
    page.wait_for_timeout(200)
    assert held, "the list of foods was asked"
    for route in held:
        route.continue_()
    page.wait_for_timeout(500)
    expect(page.get_by_role("listbox", name="Suggestions")).to_be_hidden()
    page.locator(".store-toggle", has_text="Lidl").click()  # nothing covers the filters
