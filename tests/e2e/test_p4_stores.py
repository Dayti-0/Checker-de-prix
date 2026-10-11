"""B51, B52, B53: Réglages › Localisation and Enseignes in a real Chromium.

The Courses U directory, the town table and the store shown by the site are
the SYNTHETIC fakes of tests/e2e/catalog_p4.py.
"""

import json
import re

import pytest
from playwright.sync_api import expect

from tests.e2e import catalog_p4, fake
from tests.e2e.axe import assert_accessible


def settings_page(page):
    page.goto(f"{page.base}/#/reglages")
    expect(page.get_by_role("heading", name="Réglages")).to_be_visible()
    return page


def save_postal(page, code):
    postal = page.get_by_role("textbox", name="Code postal")
    postal.fill(code)
    postal.press("Enter")


def row(page, key):
    return page.locator(f"[data-retailer={key}]")


def expected_http_error(page, status):
    """Chromium logs the expected refusal of the server (``status``) as a console error."""
    page.errors[:] = [e for e in page.errors if f"status of {status}" not in e]


def open_menu(page, label):
    page.get_by_role("button", name=f"Autres actions pour {label}").click()


def test_postal_code_then_nearest_courses_u_store(desktop):
    page = settings_page(desktop)
    postal = page.get_by_role("textbox", name="Code postal")

    # Checked in the browser: 5 digits
    save_postal(page, "123")
    expect(page.locator("#location-postal-error")).to_have_text("Saisissez 5 chiffres, par ex. 34000.")
    expect(postal).to_have_attribute("aria-invalid", "true")
    assert page.evaluate("() => document.getElementById('location-postal').validationMessage") != ""

    # Unknown postal code: an error under the field, not a success message
    save_postal(page, "99999")
    expect(page.locator("#location-postal-error")).to_have_text("Code postal inconnu : vérifiez les 5 chiffres.")
    expect(page.locator("#toast")).not_to_contain_text("Localisation enregistrée")

    # A postal code of several towns: a radio group, the first one chosen
    save_postal(page, "34480")
    expect(page.locator("#location-postal-error")).to_be_hidden()
    towns = page.get_by_role("radiogroup", name="Votre commune")
    expect(towns.get_by_role("radio")).to_have_count(5)
    expect(towns.get_by_role("radio", name="Magalas")).to_have_attribute("aria-checked", "true")

    # The nearest Courses U store is chosen by itself
    coursesu = row(page, "coursesu")
    expect(coursesu).to_contain_text("Choisi automatiquement : Super U Roujan (≈ 8 km)")
    expect(coursesu).to_contain_text("Prêt")
    assert_accessible(page, "réglages, magasin choisi automatiquement")

    # « Changer »: the 8 nearest stores, the nearest first
    coursesu.get_by_role("button", name="Changer le magasin Courses U").click()
    options = coursesu.locator(".store-option")
    expect(options).to_have_count(8)
    expect(options.first).to_contain_text("Super U Roujan")
    expect(options.first).to_contain_text("≈ 8 km")
    expect(options.first).to_contain_text("Livraison")
    expect(options.first).to_be_focused()
    assert "Eysines" not in coursesu.inner_text()
    assert_accessible(page, "liste des magasins Courses U")

    options.filter(has_text="Super U Pézenas").click()
    expect(coursesu).to_contain_text("✓ Super U Pézenas")
    expect(page.locator("#toast")).to_have_text("Magasin Courses U : Super U Pézenas")
    # A store chosen by the user is not replaced by the nearest one
    expect(coursesu).not_to_contain_text("Choisi automatiquement")

    open_menu(page, "Courses U")
    page.get_by_role("button", name="Changer de magasin Courses U").click()
    coursesu.locator(".store-option").filter(has_text="Super U Roujan").click()
    expect(coursesu).to_contain_text("✓ Super U Roujan")
    stores = page.request.get(f"{page.base}/api/settings").json()["stores"]
    assert stores["coursesu"]["url"] == "https://www.coursesu.com/drive-superu-roujan"
    assert stores["coursesu"]["auto"] is False
    expected_http_error(page, 422)


def test_town_choice_with_the_keyboard(desktop):
    page = settings_page(desktop)
    save_postal(page, "34480")
    towns = page.get_by_role("radiogroup", name="Votre commune")
    first = towns.get_by_role("radio", name="Magalas")
    expect(first).to_have_attribute("aria-checked", "true")
    first.focus()
    page.keyboard.press("ArrowRight")
    second = towns.get_by_role("radio", name="Puissalicon")
    expect(second).to_be_focused()
    expect(second).to_have_attribute("aria-checked", "true")
    expect(first).to_have_attribute("aria-checked", "false")
    expect(page.locator("#location-info")).to_have_text("Localisation : Puissalicon")
    assert page.request.get(f"{page.base}/api/settings").json()["location"]["city"] == "Puissalicon"


def test_manual_address_and_removal(desktop):
    page = settings_page(desktop)
    coursesu = row(page, "coursesu")
    expect(coursesu).to_contain_text("Indiquez votre code postal : PrixMalin choisira le magasin le plus proche.")
    coursesu.get_by_role("button", name="Choisir mon magasin Courses U").click()
    expect(coursesu).to_contain_text("Indiquez d'abord votre code postal")

    coursesu.get_by_text("Saisir l'adresse à la main").click()
    field = coursesu.get_by_role("textbox", name="Autre magasin : collez l'adresse de sa page")
    field.fill("https://exemple.fr/magasin")
    coursesu.get_by_role("button", name="Enregistrer").click()
    expect(page.locator("#toast")).to_contain_text("Adresse invalide")
    field.fill("https://www.coursesu.com/drive-superu-roujan")
    coursesu.get_by_role("button", name="Enregistrer").click()
    expect(coursesu).to_contain_text("✓ Super U Roujan")
    expect(page.locator("#toast")).to_have_text("Magasin Courses U : Super U Roujan")

    open_menu(page, "Courses U")
    page.get_by_role("button", name="Retirer le magasin Courses U").click()
    expect(coursesu).to_contain_text("Magasin à choisir")
    expect(page.locator("#toast")).to_have_text("Magasin Courses U retiré")
    expected_http_error(page, 400)


def test_intermarche_store_from_the_list(desktop):
    page = settings_page(desktop)
    save_postal(page, "34000")
    expect(page.locator("#location-info")).to_have_text("Localisation : Montpellier")
    intermarche = row(page, "intermarche")
    intermarche.get_by_role("button", name="Choisir mon magasin Intermarché").click()
    options = intermarche.locator(".store-option")
    expect(options).to_have_count(len(fake.INTERMARCHE_STORES))
    options.filter(has_text="Intermarché Hyper Lattes").click()
    expect(intermarche).to_contain_text("✓ Intermarché Hyper Lattes")
    expect(intermarche).to_contain_text("Route de Mauguio, 34970 Lattes")
    open_menu(page, "Intermarché")
    expect(page.get_by_role("button", name="Ouvrir le site Intermarché")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Autres actions pour Intermarché")).to_be_focused()
    expect(page.get_by_role("button", name="Ouvrir le site Intermarché")).to_be_hidden()


def test_store_chosen_on_the_site_is_read_back(desktop):
    page = settings_page(desktop)
    save_postal(page, "34000")
    coursesu = row(page, "coursesu")
    expect(coursesu).to_contain_text("Choisi automatiquement : U Express Montpellier Près d'Arènes")

    catalog_p4.SITE_STORE = {"link": "https://www.coursesu.com/drive-superu-pezenas"}
    open_menu(page, "Courses U")
    page.get_by_role("button", name="Ouvrir le site Courses U").click()
    banner = page.locator("#setup-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Le navigateur PrixMalin est ouvert")
    page.get_by_role("button", name="J'ai terminé").click()
    expect(banner).to_be_hidden()
    expect(coursesu).to_contain_text("✓ Super U Pézenas")
    expect(page.locator("#toast")).to_have_text("Magasin Courses U : Super U Pézenas (choisi sur le site)")
    saved = page.request.get(f"{page.base}/api/settings").json()["stores"]["coursesu"]
    assert (saved["name"], saved["auto"]) == ("Super U Pézenas", False)


def test_settings_entry_opens_the_list_of_the_retailer(desktop):
    page = desktop
    page.goto(page.base)
    page.request.post(f"{page.base}/api/settings/location", data={"postal_code": "34000"})
    page.goto(f"{page.base}/#/reglages?enseigne=intermarche")
    expect(row(page, "intermarche").locator(".store-option")).to_have_count(len(fake.INTERMARCHE_STORES))


def remote(page):
    """The page is shown on a phone: /api/browser says is_local = false."""

    def handle(route):
        response = route.fetch()
        body = response.json()
        body["is_local"] = False
        route.fulfill(response=response, body=json.dumps(body))

    page.route(re.compile(r".*/api/browser(/setup(/done)?)?$"), handle)


def test_open_the_site_from_a_phone(mobile):
    page = mobile
    remote(page)
    dialogs = []

    def answer(dialog):
        dialogs.append(dialog.message)
        dialog.accept() if len(dialogs) > 1 else dialog.dismiss()

    page.on("dialog", answer)
    settings_page(page)
    open_menu(page, "Aldi")
    page.get_by_role("button", name="Ouvrir le site Aldi").click()
    page.wait_for_timeout(300)
    assert len(dialogs) == 1
    assert dialogs[0].startswith("La page va s'ouvrir sur l'ordinateur où tourne PrixMalin.")
    assert fake.state.opened == []  # cancelled
    expect(page.locator("#setup-banner")).to_be_hidden()

    open_menu(page, "Aldi")
    page.get_by_role("button", name="Ouvrir le site Aldi").click()
    banner = page.locator("#setup-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("allez-y pour valider la vérification ou choisir le magasin")
    assert fake.state.opened == ["aldi"]
    # « J'ai terminé » stays at the bottom of the screen
    box = page.get_by_role("button", name="J'ai terminé").bounding_box()
    assert box["y"] + box["height"] <= 844 and box["y"] > 844 - 200
    assert_accessible(page, "bandeau de réglage depuis un téléphone")

    # The setup ends on the PC: the banner goes away by itself (asked every 3 s)
    page.request.post(f"{page.base}/api/browser/setup/done")
    expect(banner).to_be_hidden(timeout=8000)


def test_banner_on_the_pc(desktop):
    page = settings_page(desktop)
    open_menu(page, "Carrefour")
    page.get_by_role("button", name="Ouvrir le site Carrefour").click()
    banner = page.locator("#setup-banner")
    expect(banner).to_contain_text("Le navigateur PrixMalin est ouvert : faites vos réglages sur le site")
    page.get_by_role("button", name="J'ai terminé").click()
    expect(banner).to_be_hidden()


@pytest.mark.parametrize("width", [360, 390])
def test_no_horizontal_scroll(chromium, server, width):
    from tests.e2e.conftest import open_page

    for scale in ("0.9", "1.6"):
        context, page = open_page(chromium, server, "mobile")
        context.add_init_script(f"localStorage.setItem('prixmalin.textScale', '{scale}')")
        page.set_viewport_size({"width": width, "height": 800})
        settings_page(page)
        save_postal(page, "34480")
        coursesu = row(page, "coursesu")
        expect(coursesu).to_contain_text("Choisi automatiquement")
        coursesu.get_by_role("button", name="Changer le magasin Courses U").click()
        expect(coursesu.locator(".store-option")).to_have_count(8)
        open_menu(page, "Courses U")
        overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        context.close()
        assert overflow <= 0, f"{width} px, échelle {scale} : {overflow} px de trop"
        assert page.errors == []


def test_settings_in_dark_mode_are_accessible(dark):
    page = settings_page(dark)
    save_postal(page, "34480")
    coursesu = row(page, "coursesu")
    expect(coursesu).to_contain_text("Choisi automatiquement")
    coursesu.get_by_role("button", name="Changer le magasin Courses U").click()
    expect(coursesu.locator(".store-option")).to_have_count(8)
    open_menu(page, "Courses U")
    assert_accessible(page, "réglages en sombre")
