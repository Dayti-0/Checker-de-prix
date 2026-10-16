"""E.Leclerc Drive in the interface (P8): drive chosen by itself, list, pasted address, read-back, results.

The drives and the site are the SYNTHETIC fakes of tests/e2e/catalog_p8.py;
the products those of tests/e2e/fake.py.
"""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e import catalog_p8
from tests.e2e.axe import assert_accessible
from tests.e2e.p2_helpers import choose_view, close_toggle, no_horizontal_scroll, search

BRUGES = "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx"
PEZENAS = "https://fd3-courses.leclercdrive.fr/magasin-191201-191201-Pezenas"


def settings_page(page):
    page.goto(f"{page.base}/#/reglages")
    expect(page.get_by_role("heading", name="Réglages")).to_be_visible()
    return page


def save_postal(page, code):
    postal = page.get_by_role("textbox", name="Code postal")
    postal.fill(code)
    postal.press("Enter")


def row(page):
    return page.locator("[data-retailer=leclerc]")


def saved_drive(page):
    return page.request.get(f"{page.base}/api/settings").json()["stores"].get("leclerc")


def expected_http_error(page, status):
    """Chromium logs the expected refusal of the server (``status``) as a console error."""
    page.errors[:] = [e for e in page.errors if f"status of {status}" not in e]


def test_postal_code_chooses_the_nearest_drive_then_another_one(desktop):
    page = settings_page(desktop)
    leclerc = row(page)
    expect(leclerc).to_contain_text("Indiquez votre code postal : PrixMalin choisira le drive le plus proche.")
    save_postal(page, "34000")
    # The nearest drive, not the nearer pedestrian pick-up point
    expect(leclerc).to_contain_text("Choisi automatiquement : E.Leclerc Drive Saint-Jean-de-Védas (≈ 5 km)")
    expect(leclerc).to_contain_text("Rue de la Gare, 34430 Saint-Jean-de-Védas")
    saved = saved_drive(page)
    assert (saved["id"], saved["auto"]) == ("190501", True)
    assert saved["url"] == "https://fd3-courses.leclercdrive.fr/magasin-190501-190501-Saint-Jean-de-Vedas"
    assert_accessible(page, "réglages, drive E.Leclerc choisi automatiquement")

    # « Changer »: the 8 nearest drives and pick-up points
    leclerc.get_by_role("button", name="Changer le magasin E.Leclerc").click()
    expect(leclerc.get_by_text("Drives E.Leclerc les plus proches")).to_be_visible()
    options = leclerc.locator(".store-option")
    expect(options).to_have_count(8)
    expect(options.first).to_contain_text("E.Leclerc Drive Montpellier Comédie")
    expect(options.first).to_contain_text("même commune")
    expect(options.first).to_contain_text("Retrait piéton")
    expect(options.first).to_be_focused()
    expect(leclerc.get_by_text("Autre drive : collez l'adresse de sa page")).to_be_hidden()  # folded
    assert "Béziers Montimaran" not in leclerc.inner_text()  # the 9th and 10th are not listed
    assert_accessible(page, "liste des drives E.Leclerc")

    options.filter(has_text="Le Crès Montpellier").click()
    expect(leclerc).to_contain_text("✓ E.Leclerc Drive Le Crès Montpellier")
    expect(page.locator("#toast")).to_have_text("Drive E.Leclerc : E.Leclerc Drive Le Crès Montpellier")
    expect(leclerc).not_to_contain_text("Choisi automatiquement")
    saved = saved_drive(page)
    assert (saved["id"], saved["auto"]) == ("093401", False)

    # Removed: no drive chosen again by itself for this postal code
    leclerc.get_by_role("button", name="Autres actions pour E.Leclerc").click()
    page.get_by_role("button", name="Retirer le magasin E.Leclerc").click()
    expect(leclerc).to_contain_text("Magasin à choisir")
    page.reload()
    expect(row(page)).to_contain_text("Magasin à choisir")
    assert saved_drive(page) is None


def test_pasted_address_of_a_drive(mobile):
    page = settings_page(mobile)
    leclerc = row(page)
    leclerc.get_by_role("button", name="Choisir mon magasin E.Leclerc").click()
    expect(leclerc).to_contain_text("Indiquez d'abord votre code postal")
    leclerc.get_by_text("Saisir l'adresse à la main").click()
    field = leclerc.get_by_role("textbox", name="Autre drive : collez l'adresse de sa page")
    expect(leclerc).to_contain_text("Exemple : https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges.aspx")
    field.fill("https://www.leclercdrive.fr/region-occitanie/montpellier/")
    leclerc.get_by_role("button", name="Enregistrer l'adresse du drive E.Leclerc").click()
    expect(page.locator("#toast")).to_contain_text("Adresse invalide. Exemple : https://fd12-courses.leclercdrive.fr/")
    # The address of any page of the drive (here its search page)
    field.fill(BRUGES.replace(".aspx", "/recherche.aspx?TexteRecherche=farine"))
    leclerc.get_by_role("button", name="Enregistrer l'adresse du drive E.Leclerc").click()
    expect(leclerc).to_contain_text("✓ E.Leclerc Drive Bruges")
    expect(page.locator("#toast")).to_have_text("Drive E.Leclerc : E.Leclerc Drive Bruges")
    assert saved_drive(page)["url"] == BRUGES.removesuffix(".aspx")
    assert no_horizontal_scroll(page)
    assert_accessible(page, "drive E.Leclerc collé, téléphone")
    expected_http_error(page, 400)


def test_drive_chosen_on_the_site_is_read_back(desktop):
    page = settings_page(desktop)
    save_postal(page, "34000")
    leclerc = row(page)
    expect(leclerc).to_contain_text("Choisi automatiquement : E.Leclerc Drive Saint-Jean-de-Védas")

    catalog_p8.SITE_STORE_LECLERC = PEZENAS + ".aspx"
    leclerc.get_by_role("button", name="Autres actions pour E.Leclerc").click()
    page.get_by_role("button", name="Ouvrir le site E.Leclerc").click()
    banner = page.locator("#setup-banner")
    expect(banner).to_be_visible()
    page.get_by_role("button", name="J'ai terminé").click()
    expect(banner).to_be_hidden()
    expect(leclerc).to_contain_text("✓ E.Leclerc Drive Pézenas")
    expect(page.locator("#toast")).to_have_text("Drive E.Leclerc : E.Leclerc Drive Pézenas (choisi sur le site)")
    saved = saved_drive(page)
    assert (saved["url"], saved["auto"], saved["address"]) == (PEZENAS, False, "Route de Béziers, 34120 Pézenas")
    # Courses U was not opened: its automatic choice stays
    stores = page.request.get(f"{page.base}/api/settings").json()["stores"]
    assert stores["coursesu"]["auto"] is True


def test_results_without_then_with_a_drive(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    bar = page.get_by_test_id("unavailable")
    leclerc = bar.locator("[data-store=leclerc]")
    expect(leclerc).to_contain_text("E.Leclerc")
    expect(leclerc).to_contain_text("Magasin à choisir")
    expect(page.locator("[data-summary=leclerc]")).to_contain_text("Magasin à choisir")
    # The chip of the retailer: monogram « E »
    chip = page.locator("#store-filters label").filter(has_text="E.Leclerc")
    expect(chip.locator(".mono")).to_have_text("E")
    leclerc.get_by_role("button", name="Choisir mon magasin E.Leclerc").click()
    expect(page).to_have_url(re.compile(r"#/reglages\?enseigne=leclerc$"))

    page.request.put(f"{page.base}/api/retailers/leclerc/store", data={"url": BRUGES})
    page.goto(page.base)
    search(page, "farine")
    expect(page.get_by_test_id("unavailable").locator("[data-store=leclerc]")).to_have_count(0)
    expect(page.locator("[data-summary=leclerc]")).to_contain_text("0,82 €")
    choose_view(page, "Par enseigne")
    column = page.locator(".column[data-store=leclerc]")
    expect(column.get_by_role("heading", name=re.compile(r"^E\.Leclerc"))).to_be_visible()
    expect(column).to_contain_text("Farine de blé T45")
    # Lidl stays the cheapest
    expect(page.get_by_test_id("best-offer")).to_contain_text("Lidl")
    assert_accessible(page, "résultats avec E.Leclerc")


@pytest.mark.parametrize("theme", ["desktop", "dark"])
def test_relevance_and_colours(request, theme):
    """« huile de tournesol »: the cheaper tuna in sunflower oil is no oil (close product only)."""
    page = request.getfixturevalue(theme)
    page.goto(page.base)
    page.request.put(f"{page.base}/api/retailers/leclerc/store", data={"url": BRUGES})
    page.goto(page.base)
    search(page, "huile de tournesol")
    summary = page.locator("[data-summary=leclerc]")
    expect(summary).to_contain_text("1,92 €")
    expect(page.get_by_test_id("best-offer")).not_to_contain_text("Thon")
    choose_view(page, "Par enseigne")
    column = page.locator(".column[data-store=leclerc]")
    expect(column.locator(".product").first).to_contain_text("Huile de tournesol")
    toggle = close_toggle(page, column)
    expect(toggle).to_be_visible()
    toggle.click()
    expect(column).to_contain_text("Thon albacore à l'huile de tournesol")
    # The badge of the retailer: dark text on orange, contrast checked by axe
    badge = page.locator(".badge.leclerc-bg").first
    expect(badge).to_be_visible()
    assert_accessible(page, f"E.Leclerc, thème {theme}")


@pytest.mark.parametrize("width", [360, 390])
def test_six_retailers_fit_on_a_phone(mobile, width):
    page = mobile
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(page.base)
    page.request.put(f"{page.base}/api/retailers/leclerc/store", data={"url": BRUGES})
    page.goto(page.base)
    search(page, "farine")
    expect(page.locator("#store-filters input[type=checkbox]")).to_have_count(6)
    assert no_horizontal_scroll(page)
    settings_page(page)
    assert no_horizontal_scroll(page)


def test_assistant_proposes_three_lists(desktop):
    page = desktop
    page.goto(f"{page.base}/#/bienvenue")
    expect(page.get_by_role("heading", name="Étape 1 sur 3 : votre commune")).to_be_visible()
    expect(page.locator(".onb-card")).to_contain_text("Intermarché, Courses U et E.Leclerc les plus proches")
    save_postal(page, "34000")
    page.get_by_role("button", name="Continuer").click()
    expect(page.get_by_role("heading", name="Étape 2 sur 3 : vos magasins")).to_be_visible()
    expect(page.locator(".onb-card")).to_contain_text("Les prix d'Intermarché, de Courses U et d'E.Leclerc dépendent")
    lists = page.locator(".onb-stores")
    expect(lists).to_have_count(3)
    leclerc = page.locator(".onb-stores[data-retailer=leclerc]")
    expect(leclerc.locator("legend")).to_contain_text("Drive E.Leclerc")
    expect(leclerc.get_by_role("radio")).to_have_count(4)  # the 3 nearest, « Ne pas choisir maintenant »
    # Three lists side by side
    tops = {round(box.bounding_box()["y"]) for box in lists.all()}
    assert len(tops) == 1
    assert_accessible(page, "assistant, trois listes de magasins")
    leclerc.get_by_role("radio", name=re.compile("Lattes")).check()
    page.get_by_role("button", name="Enregistrer et continuer").click()
    expect(page.get_by_role("heading", name="Étape 3 sur 3 : essai")).to_be_visible()
    trial = page.locator(".onb-trial-row[data-retailer=leclerc]")
    expect(trial).to_contain_text("1 produit trouvé")
    saved = saved_drive(page)
    assert (saved["id"], saved["auto"]) == ("190601", False)
