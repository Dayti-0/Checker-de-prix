"""B01 (buttons of the settings) and B02 (stored XSS, links) in the real interface."""

import re

from playwright.sync_api import expect

from tests.e2e import fake
from tests.e2e.catalog_p0 import XSS_NAME

EVERY_BUTTON_IS_TYPED = (
    "() => [...document.querySelectorAll('button:not(form button)')].every((b) => b.type === 'button')"
)


def calls(page, pattern):
    """Requests to the API whose 'METHOD path' matches ``pattern`` (list filled as they happen)."""
    seen = []
    page.on(
        "request",
        lambda r: (
            seen.append(f"{r.method} {r.url.split(page.base, 1)[-1]}")
            if re.search(pattern, f"{r.method} {r.url}")
            else None
        ),
    )
    return seen


def test_settings_buttons_work(desktop):
    page = desktop
    seen = calls(page, r"/api/(retailers|browser)")
    page.goto(f"{page.base}/#/reglages")
    postal = page.get_by_role("textbox", name="Code postal")
    postal.fill("34000")
    postal.press("Enter")
    expect(page.get_by_role("status")).to_have_text("Localisation enregistrée : Montpellier")

    page.get_by_role("button", name="Choisir mon magasin Intermarché").click()
    card = page.locator("[data-retailer=intermarche]")
    stores = card.locator(".store-option")
    expect(stores).to_have_count(len(fake.INTERMARCHE_STORES))
    assert "GET /api/retailers/intermarche/stores" in seen
    stores.filter(has_text="Intermarché Hyper Lattes").click()
    expect(card).to_contain_text("✓ Intermarché Hyper Lattes")
    assert "PUT /api/retailers/intermarche/store" in seen

    page.get_by_role("button", name="Autres actions pour Intermarché").click()
    page.get_by_role("button", name="Retirer le magasin Intermarché").click()
    expect(card).to_contain_text("Magasin à choisir")
    assert "DELETE /api/retailers/intermarche/store" in seen

    page.get_by_role("button", name="Autres actions pour Courses U").click()
    page.get_by_role("button", name="Ouvrir le site Courses U").click()
    expect(page.get_by_role("button", name="J'ai terminé")).to_be_visible()
    assert "POST /api/browser/setup" in seen
    assert page.evaluate(EVERY_BUTTON_IS_TYPED)


def test_every_button_outside_a_form_is_a_plain_button(desktop):
    page = desktop
    page.goto(page.base)
    assert page.evaluate(EVERY_BUTTON_IS_TYPED)
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill("farine")
    box.press("Enter")
    expect(page.locator("[data-store=coursesu]")).to_contain_text("Ouvrir le site")
    expect(page.locator("[data-store] .spinner")).to_have_count(0)
    assert page.evaluate(EVERY_BUTTON_IS_TYPED)
    page.locator("[data-store=lidl]").get_by_role("button", name=re.compile("Ajouter")).first.click()
    page.get_by_role("link", name=re.compile("Ma liste")).click()
    page.get_by_role("button", name="Comparer mon panier").click()
    expect(page.get_by_text("Panier le moins cher")).to_be_visible()
    assert page.evaluate(EVERY_BUTTON_IS_TYPED)


def test_hostile_texts_are_shown_as_text(desktop):
    page = desktop
    page.goto(page.base)
    title = page.title()
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill("pirate")
    box.press("Enter")
    aldi = page.locator("[data-store=aldi]")
    expect(aldi.get_by_text(XSS_NAME)).to_be_visible()
    expect(aldi).to_contain_text("<b>gras</b>")
    assert page.locator("[data-store] img, [data-store] script, [data-store] b").count() == 0
    assert page.locator("a[href^='javascript' i], img[src^='javascript' i]").count() == 0

    # The product goes into the list and the basket: still plain text
    aldi.get_by_role("button", name=re.compile("Ajouter")).first.click()
    page.get_by_role("link", name=re.compile("Ma liste")).click()
    expect(page.get_by_text(f"Aldi : {XSS_NAME} (1,00 €)")).to_be_visible()
    page.get_by_role("button", name="Comparer mon panier").click()
    expect(page.get_by_role("table")).to_contain_text(XSS_NAME)
    assert page.locator("main img, a[href^='javascript' i]").count() == 0
    page.wait_for_timeout(300)  # time for an injected handler to run
    assert page.title() != "XSS-OK"
    assert "XSS" not in title


def test_unknown_retailer_cannot_be_stored(desktop):
    page = desktop
    page.goto(page.base)
    payload = {
        "query": "farine",
        "product": {"store": 'x"><img src=x onerror="document.title=\'XSS-OK\'">', "name": "Farine", "price": 1},
    }
    response = page.request.post(f"{page.base}/api/list", data=payload)
    assert response.status == 422
    assert page.request.get(f"{page.base}/api/list").json() == []
