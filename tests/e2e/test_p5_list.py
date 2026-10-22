"""« Ma liste » (B65 to B70): readable on a phone, « Annuler », aisles, notes, pasted list,
usual items, saved lists, sharing, printing, PC ↔ phone; the home card « Ma liste »."""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.axe import assert_accessible
from tests.e2e.catalog_p5 import add, call, compare, demo_list, horizontal_overflow, pdf_pages

LIDL_T45 = {
    "store": "lidl",
    "name": "Farine de blé T45",
    "brand": "Belbake",
    "price": 0.75,
    "product_url": "https://example.com/lidl/farine-de-ble-t45-0",
}
LONG_NAME = "Farine de blé type 45 extra fine spéciale pâtisserie et viennoiseries maison, sachet refermable"


def items(page):
    return call(page, "GET", "/api/list")


def open_list(page):
    page.goto(f"{page.base}/#/liste")
    expect(page.get_by_test_id("list-page")).to_be_visible()


def test_empty_list_quick_add_and_help_shown_once(desktop):
    page = desktop
    open_list(page)
    empty = page.get_by_test_id("list-empty")
    expect(empty).to_contain_text("Votre liste est vide")
    expect(empty.get_by_role("button", name=re.compile(r"^Ajouter .+ à ma liste$"))).to_have_count(3)
    assert_accessible(page, "liste vide")

    empty.get_by_role("button", name="Ajouter Lait à ma liste").click()
    expect(page.get_by_role("button", name="Modifier Lait")).to_be_visible()
    expect(page.get_by_test_id("list-count")).to_have_text("1 article")
    expect(page.get_by_role("textbox", name="Article à ajouter")).to_be_focused()
    expect(page.locator("[data-nav=list] .count")).to_have_text("1")

    help_box = page.get_by_test_id("list-help")
    expect(help_box).to_contain_text("Comment ça marche")
    help_box.get_by_role("button", name="J'ai compris").click()
    expect(help_box).to_have_count(0)
    page.reload()
    expect(page.get_by_role("button", name="Modifier Lait")).to_be_visible()
    expect(page.get_by_test_id("list-help")).to_have_count(0)  # once per device


def test_add_merge_quantity_then_undo_a_deletion(mobile):
    page = mobile
    add(page, "farine", product=LIDL_T45)
    open_list(page)
    picks = page.get_by_role("list", name="Produits choisis pour farine")
    expect(picks).to_contain_text("Lidl · Farine de blé T45")
    expect(picks).to_contain_text("0,75 €")

    # « Farine » again: the same line, one more
    field = page.get_by_role("textbox", name="Article à ajouter")
    field.fill("Farine")
    field.press("Enter")
    expect(page.get_by_role("status")).to_contain_text("« farine » : quantité 2")
    expect(page.locator(".list-row")).to_have_count(1)
    stepper = page.get_by_role("group", name="Quantité de farine")
    expect(stepper).to_contain_text("2")
    stepper.get_by_role("button", name="Augmenter la quantité de farine").click()
    expect(stepper).to_contain_text("3")
    expect(page.get_by_role("status")).to_be_hidden(timeout=5000)
    page.wait_for_function("""async () => (await (await fetch("/api/list")).json())[0].quantity === 3""")

    page.get_by_role("button", name="Supprimer farine").click()
    toast = page.get_by_role("status")
    expect(toast).to_contain_text("« farine » supprimé")
    expect(page.get_by_test_id("list-empty")).to_be_visible()
    assert items(page) == []
    toast.get_by_role("button", name="Annuler").click()
    expect(page.get_by_role("status")).to_contain_text("« farine » remis dans votre liste")
    expect(page.get_by_role("list", name="Produits choisis pour farine")).to_contain_text("0,75 €")
    [item] = items(page)
    assert (item["query"], item["quantity"], list(item["picks"])) == ("farine", 3, ["lidl"])


def test_choices_show_retailer_and_price_in_full_on_a_phone(mobile):
    page = mobile
    add(page, "farine", product={**LIDL_T45, "name": LONG_NAME})
    add(page, "farine", product={**LIDL_T45, "store": "carrefour", "name": LONG_NAME, "price": 12.45})
    for width in (390, 360):
        page.set_viewport_size({"width": width, "height": 800})
        open_list(page)
        for line in page.locator(".row-pick").all():
            price = line.locator(".pick-price")
            store_name = line.locator(".pick-store")
            expect(price).to_be_visible()
            expect(store_name).to_be_visible()
            row = line.bounding_box()
            box = price.bounding_box()
            assert box["x"] + box["width"] <= row["x"] + row["width"] + 0.5
            assert price.evaluate("(el) => el.scrollWidth <= el.clientWidth")
        assert horizontal_overflow(page) == 0, width
    assert_accessible(page, "liste sur téléphone")


def test_clearing_the_list_asks_first_and_can_be_undone(desktop):
    page = desktop
    demo_list(page)
    open_list(page)
    asked = []

    def answer(accept):
        def handler(dialog):
            asked.append(dialog.message)
            dialog.accept() if accept else dialog.dismiss()

        return handler

    page.once("dialog", answer(False))
    page.get_by_role("button", name="Vider la liste").click()
    expect(page.get_by_test_id("list-count")).to_have_text("4 articles")
    assert asked == ["Vider toute la liste (4 articles) ?"]

    page.once("dialog", answer(True))
    page.get_by_role("button", name="Vider la liste").click()
    expect(page.get_by_test_id("list-empty")).to_be_visible()
    page.get_by_role("status").get_by_role("button", name="Annuler").click()
    expect(page.get_by_test_id("list-count")).to_have_text("4 articles")
    juice = next(i for i in items(page) if i["query"] == "jus d'orange")
    assert juice["target"] == "6 L"


def test_edit_an_item_aisle_note_target_and_comparison(desktop):
    page = desktop
    demo_list(page)
    open_list(page)
    lessive = page.locator(".aisle").filter(has_text="Entretien")
    expect(lessive.get_by_role("button", name="Modifier lessive")).to_be_visible()
    page.get_by_role("button", name="Modifier lessive").click()

    sheet = page.get_by_role("dialog", name="Modifier « lessive »")
    expect(sheet).to_be_visible()
    expect(sheet.get_by_role("combobox", name="Rayon")).to_have_value("")
    expect(sheet.get_by_role("combobox", name="Rayon").locator("option").first).to_have_text("Automatique (Entretien)")
    assert_accessible(page, "feuille « Modifier »")
    # A target the basket could not read is refused, with an example (never ignored in silence)
    sheet.get_by_role("textbox", name="Quantité visée").fill("2 paquets")
    sheet.get_by_role("button", name="Enregistrer").click()
    expect(sheet.get_by_role("alert")).to_contain_text("Quantité visée non comprise : écrivez par exemple 1 kg")
    expect(sheet).to_be_visible()
    assert next(i for i in items(page) if i["query"] == "lessive")["target"] is None
    assert len(page.errors) == 1 and "status of 422" in page.errors[0]
    page.errors.clear()  # the refusal above is expected
    sheet.get_by_role("textbox", name="Quantité visée").fill("2 L")
    sheet.get_by_role("combobox", name="Rayon").select_option("Hygiène et beauté")
    sheet.get_by_role("textbox", name="Note").fill("sans parfum")
    sheet.get_by_role("checkbox", name=re.compile("Comparer les prix de cet article")).uncheck()
    sheet.get_by_role("button", name="Enregistrer").click()
    expect(sheet).to_be_hidden()
    expect(page.get_by_role("status")).to_contain_text("« lessive » modifié")

    row = page.locator(".aisle").filter(has_text="Hygiène et beauté").locator(".list-row")
    expect(row).to_contain_text("Objectif 2 L")
    expect(row).to_contain_text("Hors comparaison")
    expect(row).to_contain_text("sans parfum")
    expect(page.get_by_role("button", name="Diminuer la quantité de lessive")).to_have_count(0)  # the target counts
    item = next(i for i in items(page) if i["query"] == "lessive")
    assert (item["target"], item["note"], item["category"], item["category_set"], item["compare"]) == (
        "2 L",
        "sans parfum",
        "Hygiène et beauté",
        True,
        False,
    )

    # Échap closes the sheet, the focus goes back to the item
    page.get_by_role("button", name="Modifier lessive").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("button", name="Modifier lessive")).to_be_focused()


def test_aisles_fold_and_stay_folded(desktop):
    page = desktop
    demo_list(page)
    open_list(page)
    toggle = page.get_by_role("button", name=re.compile(r"^Crèmerie"))
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_role("button", name="Modifier beurre")).to_be_hidden()
    page.reload()
    expect(page.get_by_role("button", name=re.compile(r"^Crèmerie"))).to_have_attribute("aria-expanded", "false")
    page.get_by_role("button", name=re.compile(r"^Crèmerie")).click()
    expect(page.get_by_role("button", name="Modifier beurre")).to_be_visible()


def test_paste_a_whole_list(desktop):
    page = desktop
    add(page, "beurre")
    open_list(page)
    page.get_by_role("button", name="Coller une liste").click()
    sheet = page.get_by_role("dialog", name="Coller une liste")
    lines = [
        "2 lait demi-écrémé",
        "farine 1kg",
        "- beurre",
        "• œufs x12",
        "3x yaourts",
        "pâtes",
        "riz basmati",
        "sucre",
        "café moulu",
        "thé vert",
        "pommes",
        "carottes",
        "jambon",
        "lessive",
        "éponges",
        "papier toilette",
    ]
    sheet.get_by_role("textbox", name="Votre liste, un article par ligne").fill("\n".join(lines))
    expect(sheet).to_contain_text("Aperçu : 16 articles")
    expect(sheet.locator(".paste-lines li").filter(has_text="beurre")).to_contain_text("déjà dans la liste")
    assert_accessible(page, "feuille « Coller une liste »")
    sheet.get_by_role("button", name="Ajouter 16 articles").click()
    expect(sheet).to_be_hidden()
    expect(page.get_by_role("status")).to_contain_text("16 articles ajoutés à votre liste")
    expect(page.get_by_test_id("list-count")).to_have_text("16 articles")  # « beurre » merged
    saved = {i["query"]: i for i in items(page)}
    assert saved["beurre"]["quantity"] == 2
    assert (saved["lait demi-écrémé"]["quantity"], saved["œufs"]["target"]) == (2, "12")


def test_usual_items_in_one_tap(desktop):
    page = desktop
    for _ in range(2):
        item = add(page, "beurre")
        call(page, "DELETE", f"/api/list/{item['id']}")
    add(page, "sucre")
    open_list(page)
    usual = page.get_by_test_id("usual")
    expect(usual).to_contain_text("Vos habituels")
    usual.get_by_role("button", name="Ajouter beurre à ma liste").click()
    expect(page.get_by_role("button", name="Modifier beurre")).to_be_visible()
    expect(page.get_by_test_id("usual")).to_have_count(0)  # in the list: not proposed any more

    item = next(i for i in items(page) if i["query"] == "beurre")
    call(page, "DELETE", f"/api/list/{item['id']}")
    page.reload()
    page.get_by_test_id("usual").get_by_role("button", name="Ne plus proposer beurre").click()
    expect(page.get_by_test_id("usual")).to_have_count(0)
    assert call(page, "GET", "/api/list/usual") == []


def test_saved_lists_round_trip(desktop):
    page = desktop
    add(page, "farine", product=LIDL_T45, quantity=2)
    add(page, "jus d'orange", target="6 L")
    before = sorted((i["query"], i["quantity"], i["target"], sorted(i["picks"])) for i in items(page))
    open_list(page)
    page.get_by_role("button", name="Listes enregistrées").click()
    sheet = page.get_by_role("dialog", name="Listes enregistrées")
    expect(sheet).to_contain_text("Aucune liste enregistrée pour l'instant.")
    sheet.get_by_role("textbox", name=re.compile("Enregistrer ma liste actuelle")).fill("Courses de la semaine")
    sheet.get_by_role("button", name="Enregistrer").click()
    expect(page.get_by_role("status")).to_contain_text("Liste « Courses de la semaine » enregistrée (2 articles)")
    expect(sheet.locator(".template")).to_contain_text("2 articles")
    assert_accessible(page, "feuille « Listes enregistrées »")
    sheet.get_by_role("button", name="Fermer").click()

    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Vider la liste").click()
    expect(page.get_by_test_id("list-empty")).to_be_visible()
    page.get_by_role("button", name="Listes enregistrées").click()
    page.get_by_role("button", name="Remplacer ma liste par Courses de la semaine").click()
    expect(page.get_by_role("status")).to_contain_text("Votre liste est maintenant « Courses de la semaine »")
    expect(page.get_by_test_id("list-count")).to_have_text("2 articles")
    after = sorted((i["query"], i["quantity"], i["target"], sorted(i["picks"])) for i in items(page))
    assert after == before

    # « Ajouter à ma liste »: the quantities add up
    page.get_by_role("button", name="Listes enregistrées").click()
    page.get_by_role("button", name="Ajouter Courses de la semaine à ma liste").click()
    expect(page.get_by_role("status")).to_contain_text("« Courses de la semaine » ajoutée à votre liste")
    farine = next(i for i in items(page) if i["query"] == "farine")
    assert farine["quantity"] == 4

    page.get_by_role("button", name="Listes enregistrées").click()
    page.get_by_role("button", name="Supprimer la liste enregistrée Courses de la semaine").click()
    expect(page.get_by_role("dialog")).to_contain_text("Aucune liste enregistrée pour l'instant.")


def test_share_copy_and_files(desktop):
    page = desktop
    demo_list(page)
    open_list(page)
    page.get_by_role("button", name="Partager ou imprimer").click()
    sheet = page.get_by_role("dialog", name="Partager ou imprimer")
    text = sheet.get_by_role("textbox", name="Texte de la liste")
    expect(text).to_have_value(re.compile("beurre"))
    expect(text).to_have_value(re.compile("Entretien"))
    whatsapp = sheet.get_by_role("link", name="WhatsApp")
    expect(whatsapp).to_have_attribute("href", re.compile(r"^https://wa\.me/\?text=.*beurre"))
    expect(sheet.get_by_role("link", name="SMS")).to_have_attribute("href", re.compile(r"^sms:\?&body=.*beurre"))
    assert_accessible(page, "feuille « Partager »")

    sheet.get_by_role("button", name="Copier le texte").click()
    expect(page.get_by_role("status")).to_contain_text(re.compile("Texte (copié|sélectionné)"))

    with page.expect_download() as download:
        sheet.get_by_role("link", name="Tableur (CSV)").click()
    data = open(download.value.path(), "rb").read()  # noqa: SIM115 (small file of the test)
    assert data.startswith(b"\xef\xbb\xbf")  # accents right in Excel
    assert b"beurre" in data and b";" in data

    # Organised by retailer after a comparison of the basket
    compare(page)
    sheet.get_by_role("button", name="Fermer").click()
    page.get_by_role("button", name="Partager ou imprimer").click()
    sheet = page.get_by_role("dialog", name="Partager ou imprimer")
    sheet.get_by_role("combobox", name="Organiser la liste").select_option(label="Chez Aldi")
    expect(sheet.get_by_role("textbox", name="Texte de la liste")).to_have_value(re.compile("Aldi"))


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_list_is_accessible_in_both_themes(chromium, server, scheme):
    from tests.e2e.conftest import open_page

    context, page = open_page(chromium, server, "mobile", color_scheme=scheme)
    try:
        demo_list(page)
        add(page, "farine", product=LIDL_T45)
        open_list(page)
        expect(page.get_by_role("button", name="Modifier farine")).to_be_visible()
        assert_accessible(page, f"liste ({scheme})")
        assert horizontal_overflow(page) == 0
    finally:
        context.close()
    assert page.errors == []


def test_text_sizes_do_not_overflow_on_a_phone(mobile):
    page = mobile
    demo_list(page)
    add(page, "farine", product={**LIDL_T45, "name": LONG_NAME})
    for width in (360, 390):
        page.set_viewport_size({"width": width, "height": 800})
        for scale in ("0.9", "1.25", "1.6"):
            page.add_init_script(f"localStorage.setItem('prixmalin.textScale', '{scale}')")
            open_list(page)
            page.reload()
            expect(page.get_by_role("button", name="Modifier farine")).to_be_visible()
            assert horizontal_overflow(page) == 0, (width, scale)


def test_two_devices_stay_in_sync(chromium, server, desktop):
    pc = desktop
    add(pc, "beurre")
    open_list(pc)
    phone_context = chromium.new_context(locale="fr-FR", viewport={"width": 390, "height": 844})
    try:
        phone = phone_context.new_page()
        phone.goto(f"{server}/#/liste")
        expect(phone.get_by_role("button", name="Modifier beurre")).to_be_visible()
        # Added on the PC: shown on the phone within 10 s (polling of GET /api/list/version)
        field = pc.get_by_role("textbox", name="Article à ajouter")
        field.fill("sucre")
        field.press("Enter")
        expect(phone.get_by_role("button", name="Modifier sucre")).to_be_visible(timeout=15000)
        # Deleted on the phone: gone on the PC too
        phone.get_by_role("button", name="Supprimer beurre").click()
        expect(pc.get_by_role("button", name="Modifier beurre")).to_have_count(0, timeout=15000)
    finally:
        phone_context.close()


def test_printed_list_fits_on_one_a4_page(desktop):
    page = desktop
    demo_list(page)
    for query in ("farine", "pâtes", "riz", "café", "thé", "pommes", "carottes", "jambon", "éponges", "œufs"):
        add(page, query)
    open_list(page)
    page.get_by_role("button", name=re.compile(r"^Crèmerie")).click()  # a folded aisle is printed too
    page.emulate_media(media="print")
    expect(page.locator(".topbar")).to_be_hidden()
    expect(page.get_by_role("button", name="Vider la liste")).to_be_hidden()
    expect(page.get_by_text("beurre", exact=True)).to_be_visible()
    assert pdf_pages(page) == 1


def test_home_card_of_the_list(desktop):
    page = desktop
    page.goto(page.base)
    expect(page.get_by_role("button", name="Farine")).to_be_visible()
    expect(page.get_by_test_id("list-card")).to_have_count(0)  # empty list: no card
    demo_list(page)
    compare(page)
    page.reload()
    card = page.get_by_test_id("list-card")
    expect(card).to_contain_text("Ma liste : 4 articles")
    expect(card).to_contain_text("Panier le moins cher : Carrefour 17,39 €")
    expect(card.get_by_role("link", name="En magasin")).to_have_attribute("href", "#/courses")
    assert_accessible(page, "accueil avec la carte « Ma liste »")
    card.get_by_role("link", name="Voir ma liste").click()
    expect(page).to_have_url(re.compile(r"#/liste$"))
