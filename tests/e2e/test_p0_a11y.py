"""Accessibility of the existing views: axe finds no serious or critical violation,
in light and dark mode, on a computer and on a phone."""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.axe import assert_accessible


@pytest.fixture(params=["desktop", "dark", "mobile"])
def page(request):
    return request.getfixturevalue(request.param)


def test_views_are_accessible(page):
    page.goto(page.base)
    expect(page.get_by_role("button", name="Farine")).to_be_visible()
    assert_accessible(page, "accueil")

    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill("farine")
    box.press("Enter")
    expect(page.locator("[data-store] .spinner")).to_have_count(0)
    assert_accessible(page, "résultats")

    page.locator("[data-store=lidl]").get_by_role("button", name=re.compile("Ajouter")).first.click()
    page.get_by_role("link", name=re.compile("Ma liste")).click()
    page.get_by_role("button", name="Comparer mon panier").click()
    expect(page.get_by_text("Panier le moins cher")).to_be_visible()
    assert_accessible(page, "liste et panier")

    page.get_by_role("link", name="Réglages").first.click()
    postal = page.get_by_role("textbox", name="Code postal")
    postal.fill("34000")
    postal.press("Enter")
    page.get_by_role("button", name="Choisir mon magasin Intermarché").click()
    expect(page.locator("[data-retailer=intermarche] .store-option").first).to_be_visible()
    assert_accessible(page, "réglages")

    # Location chosen (green chip), more results to show, approximate results
    page.get_by_role("link", name="Rechercher").click()
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill("farine de blé")
    box.press("Enter")
    expect(page.locator("[data-store] .spinner")).to_have_count(0)
    expect(page.locator("#location-label")).to_have_text("34000 Montpellier")
    assert_accessible(page, "résultats approchants")
    page.locator("[data-store=aldi]").get_by_role("button", name=re.compile("Voir")).click()
    assert_accessible(page, "résultats dépliés")
    # A retailer unticked in the filters
    page.locator("#store-filters label").filter(has_text="Courses U").click()
    expect(page.locator("[data-store=coursesu]")).to_have_count(0)
    assert_accessible(page, "enseigne décochée")
