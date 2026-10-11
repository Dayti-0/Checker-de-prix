"""Search page (P2): « Tout trié », « Par enseigne », summary, close products, filters, same barcode.

The criteria of the user come first: « huile de tournesols » never shows the
tuna, the sardines, the mayonnaise or the chips in the main list, the number
of products or « Le moins cher »; they are only in « Produits proches », folded.
"""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.axe import assert_accessible
from tests.e2e.catalog_p2 import MAILLE_EAN
from tests.e2e.p2_helpers import (
    SUNFLOWER_FOOD,
    choose_view,
    close_toggle,
    main_rows,
    no_horizontal_scroll,
    offers,
    search,
)


@pytest.fixture(params=["desktop", "mobile"])
def page(request):
    return request.getfixturevalue(request.param)


def assert_unique_names(page):
    """No two buttons or links of the results with the same accessible name (CLAUDE.md, B29)."""
    names = page.locator("#results").evaluate(
        """(root) => [...root.querySelectorAll("a, button")]
            .filter((el) => el.offsetParent !== null)
            .map((el) => (el.getAttribute("aria-label") || el.textContent).replace(/\\s+/g, " ").trim())"""
    )
    assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)


def test_sunflower_oil_filters_well(page):
    page.goto(page.base)
    search(page, "huile de tournesols")
    # « Tout trié » on a phone, « Par enseigne » on a computer
    wide = page.viewport_size["width"] >= 760
    expect(page.get_by_role("radio", name="Par enseigne" if wide else "Tout trié")).to_be_checked()
    choose_view(page, "Tout trié")

    rows = main_rows(page)
    expect(rows).to_have_count(6)
    for name in rows.locator(".name-text").all_inner_texts():
        assert "huile de tournesol" in name.lower(), name
        assert not any(word.lower() in name.lower() for word in SUNFLOWER_FOOD), name
    expect(offers(page).locator(".offers-count")).to_have_text("6 produits dans 3 enseignes")

    # « Le moins cher »: the oil of Lidl at 1,79 €, not the chips at 0,79 €
    best = page.get_by_test_id("best-offer")
    expect(best).to_contain_text("Le moins cher")
    expect(best).to_contain_text("1,79 €")
    expect(best).to_contain_text("Huile de tournesol")
    expect(best.locator(".badge")).to_have_text("Lidl")
    expect(page.locator(".tag.best")).to_have_count(1)
    expect(rows.first).to_contain_text("Le moins cher")
    expect(rows.first).to_contain_text("1,79 €")
    expect(page.locator("[data-summary=lidl]")).to_contain_text("le moins cher")

    # The food in sunflower oil: only in « Produits proches », folded
    toggle = close_toggle(page)
    expect(toggle).to_have_text("Produits proches (5) dans toutes les enseignes")
    expect(toggle).to_have_accessible_name("Produits proches (5) dans toutes les enseignes")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    body = page.locator("#results-body")
    for word in SUNFLOWER_FOOD:
        expect(body).not_to_contain_text(word)
    expect(page.get_by_test_id("summary")).not_to_contain_text("Chips")
    assert_accessible(page, "tout trié")
    assert no_horizontal_scroll(page)

    toggle.click()
    expect(close_toggle(page)).to_have_attribute("aria-expanded", "true")
    close = page.get_by_test_id("close-products")
    for word in SUNFLOWER_FOOD:
        expect(close).to_contain_text(word)
    expect(close.locator(".tag.best")).to_have_count(0)
    expect(offers(page).locator(".offers-count")).to_have_text("6 produits dans 3 enseignes")
    assert_accessible(page, "produits proches ouverts")
    close_toggle(page).click()
    expect(body).not_to_contain_text("Thon")

    # « Par enseigne »: same counts, close products folded in each column
    choose_view(page, "Par enseigne")
    for key, count in (("aldi", 2), ("lidl", 2), ("carrefour", 2)):
        column = page.locator(f".column[data-store={key}]")
        expect(column.locator(".column-head .column-status")).to_have_text(f"{count} produits")
        for word in SUNFLOWER_FOOD:
            expect(column.locator(".products").first).not_to_contain_text(word)
        expect(close_toggle(page, column)).to_have_attribute("aria-expanded", "false")
    expect(page.locator(".column[data-store=lidl] .product.best")).to_contain_text("Le moins cher")
    expect(page.locator(".tag.best")).to_have_count(1)
    expect(page.get_by_role("heading", name="Aldi, 2 produits")).to_be_visible()
    # One name per retailer for the toggles, one name per product for the links
    expect(close_toggle(page, page.locator(".column[data-store=aldi]"))).to_have_accessible_name(
        "Produits proches (2) chez Aldi"
    )
    assert_unique_names(page)
    assert_accessible(page, "par enseigne")
    assert no_horizontal_scroll(page)
    choose_view(page, "Tout trié")
    assert_unique_names(page)


@pytest.mark.parametrize("query", ["huile de tournesol", "huile tournesol"])
def test_other_spellings_give_the_same_list(desktop, query):
    page = desktop
    page.goto(page.base)
    search(page, query)
    choose_view(page, "Tout trié")
    expect(main_rows(page)).to_have_count(6)
    expect(close_toggle(page)).to_have_text("Produits proches (5) dans toutes les enseignes")
    expect(page.get_by_test_id("best-offer")).to_contain_text("1,79 €")


def test_tuna_query_keeps_the_tuna(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "thon huile de tournesol")
    choose_view(page, "Tout trié")
    expect(main_rows(page).filter(has_text="Thon à l'huile de tournesol")).to_have_count(1)
    expect(page.get_by_test_id("best-offer")).to_contain_text("Thon")


def test_dark_theme(dark):
    page = dark
    page.goto(page.base)
    assert page.evaluate("() => matchMedia('(prefers-color-scheme: dark)').matches")
    search(page, "vinaigre")
    assert_accessible(page, "par enseigne, sombre")
    close = page.locator(".column[data-store=carrefour]")
    expect(close).to_contain_text("Indisponible")
    choose_view(page, "Tout trié")
    assert_accessible(page, "tout trié, sombre")
    page.get_by_role("button", name=re.compile("^Ajouter Vinaigre de cidre bio")).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    assert_accessible(page, "feuille d'ajout, sombre")
    background = page.evaluate("() => getComputedStyle(document.querySelector('.summary')).backgroundColor")
    assert background == "rgb(23, 29, 36)"  # --surface of the dark theme


def test_mixed_units_are_never_compared(desktop):
    """Crème fraîche: 4,60 €/L at Carrefour, 7,25 €/kg at Lidl."""
    page = desktop
    page.goto(page.base)
    search(page, "crème fraîche")
    page.get_by_role("radio", name=re.compile("^Prix au")).check()
    lines = page.locator(".summary-line .line-price:not(.none)")
    units = {text.split("/")[-1] for text in lines.all_inner_texts()}
    assert len(units) == 1, units
    unit = units.pop()
    expect(page.get_by_test_id("best-offer")).to_contain_text(f"Meilleur prix au {unit}")
    other = "carrefour" if unit == "kg" else "lidl"
    expect(page.locator(f"[data-summary={other}]")).to_contain_text(f"Pas de prix au {unit}")
    expect(page.get_by_test_id("summary")).not_to_contain_text("de moins que l'offre la plus chère")
    expect(page.get_by_test_id("best-offer")).to_contain_text(f"Le seul prix au {unit} trouvé.")


def test_same_barcode_is_one_line(desktop):
    page = desktop
    page.goto(page.base)
    store = {"id": "08012", "name": "Intermarché Super Montpellier", "address": "34070 Montpellier"}
    assert page.request.put(f"{page.base}/api/retailers/intermarche/store", data=store).ok
    page.reload()
    search(page, "vinaigre de vin rouge")
    choose_view(page, "Tout trié")
    group = page.locator(".offer-group")
    expect(group).to_have_count(1)
    expect(group.locator(".same-product")).to_contain_text(
        "Même produit dans 3 enseignes : Carrefour 1,95 € · Intermarché 2,05 € · Lidl 2,09 €"
    )
    expect(group.locator(".product")).to_have_count(1)
    expect(group.locator(".product")).to_contain_text("Le moins cher")
    group.get_by_role("button", name=re.compile("^Voir les 3 offres")).click()
    expect(group.locator(".product")).to_have_count(3)
    expect(group.get_by_role("button", name=re.compile("^Masquer"))).to_have_attribute("aria-expanded", "true")
    # Each offer keeps its own « + »
    expect(group.get_by_role("button", name=re.compile(r"^Ajouter .*\(Lidl, 2,09 €\)"))).to_be_visible()
    assert (
        page.request.get(f"{page.base}/api/search/lidl", params={"q": "vinaigre de vin rouge"}).json()["products"][0][
            "ean"
        ]
        == MAILLE_EAN
    )


def test_sorts_without_result_filters(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "vinaigre")
    choose_view(page, "Tout trié")
    rows = main_rows(page)
    expect(rows).to_have_count(3)  # Maille at Carrefour and Lidl: one line (same barcode)
    expect(page.locator(".offer-group")).to_contain_text("Même produit dans 2 enseignes")
    # Unavailable always last, whatever its price
    expect(rows.last).to_contain_text("Indisponible")
    expect(rows.last).to_contain_text("Vinaigre balsamique")
    # The old price of a promotion
    expect(rows.filter(has_text="Vinaigre de cidre bio").locator(".old-price")).to_have_text("au lieu de 1,49 €")
    # No filters Bio, En promo, Disponible, marques (removed at the user's request)
    expect(page.get_by_role("group", name="Filtrer les résultats")).to_have_count(0)
    for name in ("Bio", "En promo", "Disponible", "Marque distributeur", "Marque nationale"):
        expect(page.get_by_role("button", name=re.compile(f"^{name}"))).to_have_count(0)

    # Sorts: radio group, arrows of the keyboard, remembered on the device
    price = page.get_by_role("radio", name="Prix", exact=True)
    expect(price).to_be_checked()
    price.focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("radio", name=re.compile("^Prix au"))).to_be_checked()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("radio", name="Promos")).to_be_checked()
    expect(rows.first).to_contain_text("Vinaigre de cidre bio")
    page.reload()
    expect(page.get_by_role("radio", name="Promos")).to_be_checked()
    expect(page.get_by_role("radio", name="Tout trié")).to_be_checked()


def test_retailers_without_results_are_one_compact_bar(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    bar = page.get_by_test_id("unavailable")
    expect(bar).to_contain_text("2 enseignes indisponibles")
    intermarche = bar.locator("[data-store=intermarche]")
    expect(intermarche).to_contain_text("Magasin à choisir")
    coursesu = bar.locator("[data-store=coursesu]")
    expect(coursesu).to_contain_text("Vérification requise")
    expect(coursesu.get_by_role("button", name="Ouvrir le site Courses U")).to_be_visible()
    expect(coursesu.get_by_role("button", name="Réessayer Courses U")).to_be_visible()
    # At most 56 px high, every column with products on the first row
    assert bar.bounding_box()["height"] <= 56
    tops = {round(page.locator(f".column[data-store={k}]").bounding_box()["y"]) for k in ("aldi", "lidl", "carrefour")}
    assert len(tops) == 1
    # Status by an icon and a text, not only by a colour
    expect(intermarche.locator("svg")).to_have_count(1)
    expect(page.locator("[data-summary=intermarche]")).to_contain_text("Magasin à choisir")
    intermarche.get_by_role("button", name="Choisir mon magasin Intermarché").click()
    expect(page).to_have_url(re.compile(r"#/reglages\?enseigne=intermarche$"))


def test_no_result_is_one_block_with_shorter_searches(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "chocolat noir 100 g")
    block = page.get_by_test_id("no-results")
    expect(block).to_have_count(1)
    expect(block.get_by_role("heading")).to_have_text("Aucun produit pour « chocolat noir 100 g »")
    expect(block.get_by_role("button", name=re.compile("^Rechercher"))).to_have_text(
        ["chocolat noir", "chocolat", "noir"]
    )
    # The retailers without the product are not listed a second time in the bar
    expect(page.get_by_test_id("unavailable")).to_contain_text("2 enseignes indisponibles :")
    expect(page.get_by_test_id("unavailable")).not_to_contain_text("sans produit")
    # The summary would only repeat it: hidden, the block comes first
    expect(page.get_by_test_id("summary")).to_be_hidden()
    assert_accessible(page, "aucun produit")
    block.get_by_role("button", name="Ajouter « chocolat noir 100 g » à ma liste quand même").click()
    expect(page.get_by_role("status")).to_contain_text("« chocolat noir 100 g » ajouté à votre liste")
    expect(page.locator("[data-nav=list] .count")).to_have_text("1")
    block.get_by_role("button", name="Rechercher « chocolat »").click()
    expect(page).to_have_url(re.compile(r"#/recherche\?q=chocolat$"))
    expect(page.get_by_test_id("no-results").get_by_role("heading")).to_have_text("Aucun produit pour « chocolat »")
    # A search with products shows the summary again
    search(page, "vinaigre")
    expect(page.get_by_test_id("summary")).to_be_visible()
    expect(page.get_by_test_id("no-results")).to_have_count(0)


def test_product_rows(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    lidl = page.locator(".column[data-store=lidl]")
    row = lidl.locator(".product").first
    # Name, brand in title case, quantity, price and price per kg
    expect(row.locator(".meta")).to_have_text("Belbake · 1 kg")
    expect(row.locator(".unit")).to_have_text("0,75 €/kg")
    link = row.get_by_role("link")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_contain_text("(nouvel onglet)")
    # At most 96 px for a name on one line
    assert row.bounding_box()["height"] <= 96
    # Unavailable: label, price struck out, « + » disabled
    francine = page.locator(".column[data-store=carrefour] .product.unavailable")
    expect(francine.locator(".tag.out")).to_have_text("Indisponible")
    assert francine.locator(".price").evaluate("el => getComputedStyle(el).textDecorationLine") == "line-through"
    expect(francine.get_by_role("button", name=re.compile("^Ajouter"))).to_be_disabled()
    # The promotion is never cut
    promo = page.locator(".column[data-store=carrefour] .tag.promo").first
    assert promo.evaluate("el => el.scrollWidth <= el.clientWidth")
    # Unique names of the buttons
    names = page.locator("#results button").evaluate_all(
        "els => els.filter((b) => b.offsetParent).map((b) => b.getAttribute('aria-label') || b.textContent.trim())"
    )
    assert len(names) == len(set(names)), names
    # One h2 per retailer
    expect(page.get_by_role("heading", name="Lidl, 1 produit")).to_be_visible()
    expect(page.locator(".column[data-store=aldi] .column-foot")).to_have_text("2 produits lus")
