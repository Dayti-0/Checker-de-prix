"""Layout of the search page on small screens, retailer filters (B30), accessibility in both themes."""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.axe import assert_accessible
from tests.e2e.conftest import CSP_WATCH
from tests.e2e.p2_helpers import choose_view, close_toggle, no_horizontal_scroll, search, wait_done

SCALES = [0.9, 1, 1.125, 1.25, 1.4, 1.6]


@pytest.fixture
def narrow(chromium, server):
    """Phones of 360 and 390 px, light theme: (open(width, scale) → page)."""
    contexts = []

    def open_page(width, scale=1):
        context = chromium.new_context(
            locale="fr-FR", viewport={"width": width, "height": 780}, is_mobile=True, has_touch=True
        )
        context.add_init_script(CSP_WATCH)
        context.add_init_script(f"localStorage.setItem('prixmalin.textScale', '{scale}')")
        contexts.append(context)
        page = context.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.on("console", lambda m: page.errors.append(m.text) if m.type == "error" else None)
        return page

    yield open_page
    for context in contexts:
        context.close()


@pytest.mark.parametrize("width", [360, 390])
def test_no_horizontal_scroll_at_every_text_size(narrow, server, width):
    for scale in SCALES:
        page = narrow(width, scale)
        page.goto(f"{server}/#/recherche?q=huile%20de%20tournesols")
        wait_done(page)
        assert no_horizontal_scroll(page), (width, scale, "tout trié")
        close_toggle(page).click()
        assert no_horizontal_scroll(page), (width, scale, "produits proches")
        choose_view(page, "Par enseigne")
        assert no_horizontal_scroll(page), (width, scale, "par enseigne")
        page.get_by_role("button", name=re.compile("^Ajouter Huile de tournesol")).first.click()
        assert no_horizontal_scroll(page), (width, scale, "feuille d'ajout")
        page.keyboard.press("Escape")
        page.goto(f"{server}/#/recherche?q=chocolat%20noir%20100%20g")
        wait_done(page)
        assert no_horizontal_scroll(page), (width, scale, "aucun produit")
        page.goto(f"{server}/#/")
        expect(page.get_by_test_id("recent-card")).to_contain_text("Recherches récentes")
        assert no_horizontal_scroll(page), (width, scale, "accueil")
        assert page.errors == [], page.errors
        page.context.close()


def test_toolbar_and_filters_on_a_small_phone(narrow, server):
    page = narrow(360)
    page.goto(f"{server}/#/recherche?q=vinaigre")
    wait_done(page)
    # View and « Actualiser » on one line, every control 44 px high at least
    view = page.locator("#view-switch").bounding_box()
    refresh = page.get_by_role("button", name="Actualiser les prix").bounding_box()
    assert abs(view["y"] - refresh["y"]) < 4
    for name in ("Tout trié", "Par enseigne", "Prix", "Promos", "Pertinence"):
        box = page.locator("label", has=page.get_by_role("radio", name=name, exact=True)).bounding_box()
        assert box["height"] >= 44, name
    # Retailer filters: one row of 48 px at most, that scrolls sideways
    filters = page.locator("#store-filters")
    assert filters.bounding_box()["height"] <= 48
    row = page.locator(".store-chips-row")
    assert row.evaluate("el => el.scrollWidth > el.clientWidth")
    assert no_horizontal_scroll(page)


def test_retailer_filters(desktop):
    page = desktop
    page.goto(page.base)
    group = page.get_by_role("group", name="Enseignes comparées")
    expect(group.get_by_role("checkbox")).to_have_count(6)
    aldi = group.get_by_role("checkbox", name=re.compile("Aldi"))
    expect(aldi).to_be_checked()
    # Ticked and unticked are told by a mark, not only by the colour
    label = page.locator(".store-toggle", has=page.locator("input[value=aldi]"))
    expect(label.locator("use")).to_have_attribute("href", "/static/icons.svg#check")
    label.click()
    expect(aldi).not_to_be_checked()
    expect(label.locator("use")).to_have_attribute("href", "/static/icons.svg#plus")
    # Focus visible on the chip
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    focused = page.locator(".store-toggle:has(input:focus-visible)")
    expect(focused).to_have_count(1)
    assert focused.evaluate("el => getComputedStyle(el).boxShadow") != "none"
    # The choice is remembered on the device
    page.reload()
    expect(
        page.get_by_role("group", name="Enseignes comparées").get_by_role("checkbox", name=re.compile("Aldi"))
    ).not_to_be_checked()
    # The last ticked retailer cannot be unticked: said to the user
    for name in ("Lidl", "Carrefour", "Intermarché", "Courses U"):
        page.locator(".store-toggle", has_text=name).click()
    page.locator(".store-toggle", has_text="E.Leclerc").click()
    expect(page.get_by_role("checkbox", name=re.compile("E.Leclerc"))).to_be_checked()
    expect(page.get_by_role("status")).to_have_text("Gardez au moins une enseigne cochée.")
    assert_accessible(page, "filtres des enseignes")


def test_a_retailer_ticked_later_is_searched(desktop):
    page = desktop
    page.goto(page.base)
    page.locator(".store-toggle", has_text="Lidl").click()
    search(page, "farine")
    expect(page.locator("[data-store=lidl]")).to_have_count(0)
    expect(page.locator("[data-summary=lidl]")).to_have_count(0)
    page.locator(".store-toggle", has_text="Lidl").click()
    wait_done(page)
    expect(page.locator(".column[data-store=lidl]")).to_contain_text("Farine de blé T45")
    expect(page.get_by_test_id("best-offer")).to_contain_text("0,75 €")


def test_mobile_dark_theme_is_accessible(chromium, server, request):
    from tests.e2e.conftest import page_fixture

    gen = page_fixture(request, chromium, server, "mobile", color_scheme="dark")
    page = next(gen)
    try:
        page.goto(page.base)
        assert_accessible(page, "accueil, téléphone sombre")
        search(page, "huile de tournesols")
        assert_accessible(page, "tout trié, téléphone sombre")
        close_toggle(page).click()
        choose_view(page, "Par enseigne")
        assert_accessible(page, "par enseigne, téléphone sombre")
        search(page, "chocolat noir")
        assert_accessible(page, "aucun produit, téléphone sombre")
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_five_best_offers_in_the_first_two_screens(mobile):
    """B25: on a phone of 390 px, the 5 best offers are in the first two screens (two retailers unavailable)."""
    page = mobile
    page.goto(page.base)
    # A drive E.Leclerc is chosen: only Intermarché and Courses U are unavailable
    drive = "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges"
    page.request.put(f"{page.base}/api/retailers/leclerc/store", data={"url": drive})
    search(page, "huile de tournesols")
    expect(page.get_by_role("radio", name="Tout trié")).to_be_checked()
    rows = page.locator("[data-testid=offers] .offer-list > li")
    expect(rows).to_have_count(7)
    bottom = rows.nth(4).evaluate("el => el.getBoundingClientRect().bottom + window.scrollY")
    assert bottom <= 2 * page.viewport_size["height"], bottom
    # « Magasin à choisir »: « Choisir » only, « Vérification requise »: « Ouvrir le site » and « Réessayer »
    bar = page.get_by_test_id("unavailable")
    expect(bar.locator("[data-store=intermarche]").get_by_role("button")).to_have_text(["Choisir"])
    expect(bar.locator("[data-store=coursesu]").get_by_role("button")).to_have_text(["Ouvrir le site", "Réessayer"])
