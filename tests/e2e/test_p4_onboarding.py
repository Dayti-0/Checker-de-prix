"""B54: first-launch assistant (#/bienvenue) and the home card « Finissez la configuration »."""

import re

import pytest
from playwright.sync_api import expect

from backend.services import settings as settings_service
from tests.e2e.axe import assert_accessible

# Width beyond the screen: on a phone the layout viewport grows with the page,
# so the visible width is the reference (not innerWidth)
OVERFLOW = "() => document.documentElement.scrollWidth - Math.round(window.visualViewport.width)"


@pytest.fixture
def first_launch(monkeypatch):
    """The assistant opens by itself, as on a real first launch (off in the other tests)."""
    monkeypatch.setattr(settings_service, "AUTO_ONBOARDING", True)


def step_title(page):
    return page.locator("#onb-step-title")


def test_assistant_on_the_first_launch(first_launch, desktop):
    page = desktop
    page.goto(page.base)
    expect(page).to_have_url(re.compile(r"#/bienvenue$"))
    expect(step_title(page)).to_have_text("Étape 1 sur 3 : votre commune")
    expect(page.locator(".onb-steps [aria-current=step]")).to_contain_text("Votre commune")
    next_button = page.get_by_role("button", name="Continuer")
    expect(next_button).to_be_disabled()
    assert_accessible(page, "assistant, étape 1")

    postal = page.get_by_role("textbox", name="Code postal")
    postal.fill("34000")
    postal.press("Enter")
    expect(next_button).to_be_enabled()
    next_button.click()

    # Step 2: the 3 nearest stores of each retailer, the nearest chosen
    expect(step_title(page)).to_have_text("Étape 2 sur 3 : vos magasins")
    expect(step_title(page)).to_be_focused()
    intermarche = page.get_by_role("group", name=re.compile("Magasin Intermarché"))
    coursesu = page.get_by_role("group", name=re.compile("Magasin Courses U"))
    expect(intermarche.get_by_role("radio")).to_have_count(4)  # 3 stores + « Ne pas choisir maintenant »
    expect(coursesu.get_by_role("radio")).to_have_count(4)
    expect(intermarche.get_by_role("radio").first).to_be_checked()
    expect(coursesu.get_by_role("radio", name=re.compile("U Express Montpellier"))).to_be_checked()
    assert_accessible(page, "assistant, étape 2")
    intermarche.get_by_role("radio", name=re.compile("Intermarché Hyper Lattes")).check()
    page.get_by_role("button", name="Enregistrer et continuer").click()

    # Step 3: trial search « lait », state of each retailer and how to fix it
    expect(step_title(page)).to_have_text("Étape 3 sur 3 : essai")
    rows = page.locator(".onb-trial-row")
    expect(rows).to_have_count(5)
    expect(page.locator(".onb-trial .spinner")).to_have_count(0)
    expect(rows.filter(has_text="Aldi")).to_contain_text("1 produit trouvé")
    expect(rows.filter(has_text="Intermarché")).to_contain_text("Prêt")
    expect(rows.filter(has_text="Courses U")).to_contain_text("Vérification requise")
    expect(page.get_by_role("button", name="Faire la vérification sur le site Courses U")).to_be_visible()
    assert_accessible(page, "assistant, étape 3")
    stores = page.request.get(f"{page.base}/api/settings").json()["stores"]
    assert stores["intermarche"]["name"] == "Intermarché Hyper Lattes"
    assert stores["coursesu"]["name"] == "U Express Montpellier Près d'Arènes"

    page.get_by_role("button", name="Terminer").click()
    expect(page).to_have_url(re.compile(r"#/$"))
    expect(page.locator("#toast")).to_have_text("C'est prêt : tapez un produit pour comparer les prix.")
    # Everything is set: no configuration card
    expect(page.locator("[data-testid=setup-card]")).to_have_count(0)
    status = page.request.get(f"{page.base}/api/settings/onboarding").json()
    assert status["done"] and not status["needed"]

    # Only once
    page.reload()
    expect(page.get_by_role("searchbox", name="Produit à rechercher")).to_be_visible()
    page.wait_for_timeout(300)
    expect(page).not_to_have_url(re.compile("bienvenue"))


def test_assistant_is_shown_once_even_when_left(first_launch, desktop):
    page = desktop
    page.goto(page.base)
    expect(page).to_have_url(re.compile(r"#/bienvenue$"))
    page.get_by_role("link", name="Rechercher").click()
    expect(page.get_by_role("searchbox", name="Produit à rechercher")).to_be_visible()
    page.reload()
    expect(page.get_by_role("searchbox", name="Produit à rechercher")).to_be_visible()
    page.wait_for_timeout(300)
    expect(page).not_to_have_url(re.compile("bienvenue"))
    # The configuration card leads back to it
    card = page.locator("[data-testid=setup-card]")
    expect(card).to_contain_text("votre code postal")
    card.get_by_role("link", name="Lancer l'assistant").click()
    expect(step_title(page)).to_have_text("Étape 1 sur 3 : votre commune")


def test_skip_back_and_fix(mobile):
    page = mobile
    page.goto(f"{page.base}/#/bienvenue")
    page.get_by_role("button", name="Passer").click()
    expect(step_title(page)).to_have_text("Étape 2 sur 3 : vos magasins")
    expect(page.locator(".onb-card")).to_contain_text("Sans code postal")
    page.get_by_role("button", name="Retour").click()
    expect(step_title(page)).to_have_text("Étape 1 sur 3 : votre commune")
    expect(step_title(page)).to_be_focused()
    page.get_by_role("button", name="Passer").click()
    page.get_by_role("button", name="Continuer").click()
    expect(step_title(page)).to_have_text("Étape 3 sur 3 : essai")
    intermarche = page.locator(".onb-trial-row").filter(has_text="Intermarché")
    expect(intermarche).to_contain_text("Magasin à choisir")
    assert_accessible(page, "assistant sur téléphone")
    overflow = page.evaluate(OVERFLOW)
    assert overflow <= 0
    page.get_by_role("button", name="Choisir mon magasin Intermarché").click()
    expect(step_title(page)).to_have_text("Étape 2 sur 3 : vos magasins")


def test_home_card_while_the_setup_is_incomplete(desktop):
    page = desktop
    page.goto(page.base)
    card = page.locator("[data-testid=setup-card]")
    expect(card).to_contain_text("votre code postal, votre magasin Intermarché et votre magasin Courses U")
    assert_accessible(page, "accueil avec la carte de configuration")
    page.request.post(f"{page.base}/api/settings/location", data={"postal_code": "34000"})
    page.request.put(
        f"{page.base}/api/retailers/intermarche/store", data={"id": "08012", "name": "Intermarché Super Montpellier"}
    )
    page.reload()
    # Courses U: the nearest store is chosen by itself once the settings are loaded
    expect(card).to_have_count(0)
    stores = page.request.get(f"{page.base}/api/settings").json()["stores"]
    assert stores["coursesu"]["auto"] is True


def test_assistant_in_dark_mode(dark):
    page = dark
    page.goto(f"{page.base}/#/bienvenue")
    postal = page.get_by_role("textbox", name="Code postal")
    postal.fill("34480")
    postal.press("Enter")
    expect(page.get_by_role("radio", name="Magalas")).to_be_visible()
    assert_accessible(page, "assistant en sombre, étape 1")
    page.get_by_role("button", name="Continuer").click()
    expect(page.get_by_role("group", name=re.compile("Magasin Courses U")).get_by_role("radio")).to_have_count(4)
    assert_accessible(page, "assistant en sombre, étape 2")


@pytest.mark.parametrize("width", [360, 390])
def test_no_horizontal_scroll_in_the_new_views(chromium, server, width):
    from tests.e2e.conftest import open_page

    for scale in ("0.9", "1.6"):
        context, page = open_page(chromium, server, "mobile")
        context.add_init_script(f"localStorage.setItem('prixmalin.textScale', '{scale}')")
        page.set_viewport_size({"width": width, "height": 800})
        page.goto(page.base)
        page.request.post(f"{page.base}/api/settings/location", data={"postal_code": "34480"})
        page.request.get(f"{page.base}/api/search", params={"q": "farine"})
        overflows = {}
        page.goto(f"{page.base}/#/etat")
        expect(page.locator(".status-card")).to_have_count(5)
        overflows["état"] = page.evaluate(OVERFLOW)
        page.goto(f"{page.base}/#/bienvenue")
        page.get_by_role("button", name="Continuer").click()
        expect(page.locator(".onb-store input")).to_have_count(8)
        overflows["assistant, magasins"] = page.evaluate(OVERFLOW)
        page.get_by_role("button", name="Enregistrer et continuer").click()
        expect(page.locator(".onb-trial .spinner")).to_have_count(0)
        overflows["assistant, essai"] = page.evaluate(OVERFLOW)
        page.goto(page.base)
        expect(page.get_by_role("searchbox", name="Produit à rechercher")).to_be_visible()
        overflows["accueil"] = page.evaluate(OVERFLOW)
        errors = list(page.errors)
        context.close()
        assert all(v <= 0 for v in overflows.values()), f"{width} px, échelle {scale} : {overflows}"
        assert errors == []
