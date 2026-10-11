"""Adding a product of the results to « Ma liste » (B32): the sheet, « ✓ », « Annuler »."""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.axe import assert_accessible
from tests.e2e.p2_helpers import choose_view, search

T45 = re.compile(r"^Ajouter Farine de blé T45 Belbake \(Lidl, 0,75 €\) à ma liste$")
T45_LISTED = "Retirer Farine de blé T45 Belbake (Lidl, 0,75 €) de ma liste"


def list_items(page):
    return page.request.get(f"{page.base}/api/list").json()


def boxes_overlap(a, b):
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def test_add_exactly_this_product_then_undo(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    plus = page.get_by_role("button", name=T45)
    plus.click()

    sheet = page.get_by_role("dialog", name="Ajouter à ma liste")
    expect(sheet).to_be_visible()
    expect(sheet).to_contain_text("Farine de blé T45")
    expect(sheet.get_by_role("radio", name=re.compile("Exactement ce produit chez Lidl"))).to_be_checked()
    expect(sheet.get_by_role("radio", name=re.compile("« farine », le moins cher sera choisi"))).not_to_be_checked()
    expect(sheet.get_by_role("spinbutton", name="Quantité")).to_have_value("1")
    expect(sheet.get_by_role("button", name="Ajouter")).to_be_focused()
    assert_accessible(page, "feuille d'ajout")
    sheet.get_by_role("button", name="Un de plus").click()
    sheet.get_by_role("button", name="Ajouter").click()
    expect(sheet).to_be_hidden()

    toast = page.get_by_role("status").filter(has_text="Ajouté")
    expect(toast).to_contain_text("Ajouté à « farine »")
    expect(toast.get_by_role("button", name="Voir la liste")).to_be_visible()
    expect(toast.get_by_role("button", name="Annuler")).to_be_visible()
    expect(page.locator("[data-nav=list] .count")).to_have_text("1")
    items = list_items(page)
    assert [(i["query"], i["quantity"], list(i["picks"])) for i in items] == [("farine", 2, ["lidl"])]

    # « ✓ »: the button says the product is in the list, also after a reload
    listed = page.get_by_role("button", name=T45_LISTED)
    expect(listed).to_be_visible()
    expect(listed).to_be_focused()  # the focus came back to it
    page.reload()
    expect(page.get_by_role("button", name=T45_LISTED)).to_be_visible()

    # « Annuler » puts the list back as it was
    page.get_by_role("button", name=T45_LISTED).click()  # « ✓ » removes it
    toast = page.get_by_role("status")
    expect(toast).to_contain_text("Farine de blé T45 (Lidl) retiré de votre liste")
    assert list_items(page) == []
    toast.get_by_role("button", name="Annuler").click()
    expect(page.get_by_role("button", name=T45_LISTED)).to_be_visible()
    assert [(i["quantity"], list(i["picks"])) for i in list_items(page)] == [(2, ["lidl"])]


def test_undo_an_addition(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    page.get_by_role("button", name=T45).click()
    page.get_by_role("dialog").get_by_role("button", name="Ajouter").click()
    page.get_by_role("status").get_by_role("button", name="Annuler").click()
    expect(page.get_by_role("status")).to_have_text("Ajout annulé")
    expect(page.get_by_role("button", name=T45)).to_be_visible()
    assert list_items(page) == []


def test_replacing_the_product_of_a_retailer(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    page.get_by_role("button", name=re.compile(r"^Ajouter Farine de blé T55")).click()
    page.get_by_role("dialog").get_by_role("button", name="Ajouter").click()
    expect(page.get_by_role("button", name=re.compile(r"^Retirer Farine de blé T55"))).to_be_visible()

    page.get_by_role("button", name=re.compile(r"^Ajouter Farine de sarrasin")).click()
    sheet = page.get_by_role("dialog")
    expect(sheet.locator("#sheet-note")).to_have_text("Remplace Farine de blé T55 (Aldi).")
    expect(sheet.get_by_role("button", name="Enregistrer")).to_be_visible()
    sheet.get_by_role("button", name="Enregistrer").click()
    expect(page.get_by_role("status")).to_contain_text("Ajouté à « farine » · Remplace Farine de blé T55 (Aldi)")
    expect(page.get_by_role("button", name=re.compile(r"^Retirer Farine de sarrasin"))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"^Ajouter Farine de blé T55"))).to_be_visible()
    # « Annuler »: the first choice comes back
    page.get_by_role("status").get_by_role("button", name="Annuler").click()
    expect(page.get_by_role("button", name=re.compile(r"^Retirer Farine de blé T55"))).to_be_visible()
    [item] = list_items(page)
    assert item["picks"]["aldi"]["name"] == "Farine de blé T55"


def test_the_search_only(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    page.get_by_role("button", name=T45).click()
    sheet = page.get_by_role("dialog")
    sheet.get_by_role("radio", name=re.compile("« farine », le moins cher sera choisi")).check()
    sheet.get_by_role("button", name="Ajouter").click()
    expect(page.get_by_role("status")).to_contain_text("« farine » ajouté à votre liste")
    [item] = list_items(page)
    assert (item["query"], item["picks"]) == ("farine", {})
    # The product itself is not « ✓ »: only the search is in the list
    expect(page.get_by_role("button", name=T45)).to_be_visible()
    page.get_by_role("status").get_by_role("button", name="Voir la liste").click()
    expect(page).to_have_url(re.compile(r"#/liste$"))


def test_escape_closes_the_sheet_and_gives_the_focus_back(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    plus = page.get_by_role("button", name=T45)
    plus.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_be_hidden()
    expect(plus).to_be_focused()
    assert list_items(page) == []


@pytest.mark.parametrize("view", ["Tout trié", "Par enseigne"])
def test_on_a_phone_the_message_hides_no_main_action(mobile, view):
    page = mobile
    page.goto(page.base)
    search(page, "farine")
    choose_view(page, view)
    plus = page.get_by_role("button", name=T45)
    plus.click()
    sheet = page.get_by_role("dialog")
    box = sheet.bounding_box()
    viewport = page.viewport_size
    assert box["y"] + box["height"] >= viewport["height"] - 1  # at the bottom of the screen
    assert box["width"] >= viewport["width"] - 1
    sheet.get_by_role("button", name="Ajouter").click()
    toast = page.locator("#toast")
    expect(toast).to_be_visible()
    listed = page.get_by_role("button", name=T45_LISTED)
    expect(listed).to_be_in_viewport()
    for target in (listed, page.get_by_role("button", name="Comparer")):
        target_box = target.bounding_box()
        if target_box:
            assert not boxes_overlap(toast.bounding_box(), target_box)
