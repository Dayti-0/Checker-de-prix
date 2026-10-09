"""Smoke tests: the main journeys, on desktop and on a phone.

They only use roles, texts, ids and data attributes so that they keep passing
whatever the look of the interface.
"""

import re

import pytest
from playwright.sync_api import expect

STORES = ["aldi", "lidl", "carrefour", "intermarche", "coursesu"]


@pytest.fixture(params=["desktop", "mobile"])
def page(request):
    return request.getfixturevalue(request.param)


def search(page, query="farine"):
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill(query)
    box.press("Enter")
    expect(page).to_have_url(re.compile(rf"#/recherche\?q={query}$"))
    for key in STORES:  # every retailer answered
        expect(page.locator(f"[data-store={key}] .spinner")).to_have_count(0)


def test_search_farine(page):
    page.goto(page.base)
    expect(page.get_by_role("searchbox", name="Produit à rechercher")).to_be_visible()
    search(page)
    expect(page).to_have_title("farine – Rechercher · PrixMalin")

    aldi = page.locator("[data-store=aldi]")
    expect(aldi).to_contain_text("Farine de blé T55")
    expect(aldi).to_contain_text("0,79 €")
    lidl = page.locator("[data-store=lidl]")
    expect(lidl).to_contain_text("0,75 €")
    expect(lidl).to_contain_text("Le moins cher")
    carrefour = page.locator("[data-store=carrefour]")
    expect(carrefour).to_contain_text("2ème à -50%")
    expect(carrefour).to_contain_text("Indisponible")
    expect(page.locator("[data-store=intermarche]")).to_contain_text("Magasin à choisir")
    coursesu = page.locator("[data-store=coursesu]")
    expect(coursesu.get_by_role("button", name="Ouvrir le site")).to_be_visible()
    expect(page.locator("[data-store]").get_by_text("Huile de tournesol")).to_have_count(0)


def test_add_to_list_and_compare_the_basket(page):
    page.goto(page.base)
    search(page)
    page.locator("[data-store=lidl]").get_by_role("button", name=re.compile("Ajouter")).first.click()
    expect(page.get_by_role("status")).to_have_text("Ajouté : Farine de blé T45 (Lidl)")

    page.get_by_role("link", name=re.compile("Ma liste")).click()
    expect(page).to_have_url(re.compile(r"#/liste$"))
    expect(page).to_have_title("Ma liste · PrixMalin")
    expect(page.get_by_text("Lidl : Farine de blé T45 (0,75 €)")).to_be_visible()

    page.get_by_role("button", name="Comparer mon panier").click()
    expect(page.get_by_text("Panier le moins cher")).to_be_visible()
    expect(page.get_by_text("En achetant chaque article là où il est le moins cher")).to_contain_text("0,75 €")
    expect(page.get_by_role("table")).to_contain_text("Farine de blé T45")


def test_settings_open(page):
    page.goto(page.base)
    page.get_by_role("link", name="Réglages").first.click()
    expect(page).to_have_url(re.compile(r"#/reglages$"))
    expect(page).to_have_title("Réglages · PrixMalin")
    expect(page.get_by_role("heading", name="Réglages")).to_be_visible()
    expect(page.get_by_role("textbox", name="Code postal")).to_be_visible()
    for label in ("Aldi", "Lidl", "Carrefour", "Intermarché", "Courses U"):
        expect(page.locator("[data-retailer]").filter(has_text=label).first).to_be_visible()
    expect(page.get_by_role("button", name="Ouvrir le site")).to_have_count(5)
