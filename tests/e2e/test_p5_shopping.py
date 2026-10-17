"""Mode « En magasin » (#/courses, B64): where to shop, ticks with one hand, offline ticks,
« Terminer », the list by aisle without a comparison."""

import re
import time

import httpx
import pytest
from playwright.sync_api import expect

from tests.e2e.axe import assert_accessible
from tests.e2e.catalog_p5 import HEADERS, call, compare, demo_list, horizontal_overflow

WAKE_LOCK = """
window.__wake = 0;
Object.defineProperty(navigator, "wakeLock", {
    configurable: true,
    value: { request: async () => { window.__wake += 1; return { release: async () => {} }; } },
});
"""


def wait_until(condition, seconds=15.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def checked(base, query):
    """Whether the server has ``query`` ticked (read without the browser, which may be offline)."""
    items = httpx.get(f"{base}/api/list", headers=HEADERS).json()
    return next(i for i in items if i["query"] == query)["checked"]


def follow_carrefour(page):
    page.goto(f"{page.base}/#/courses")
    chooser = page.get_by_test_id("trip-chooser")
    chooser.get_by_role("link", name=re.compile(r"^Tout chez Carrefour")).click()
    expect(page).to_have_url(re.compile(r"#/courses\?plan=0$"))
    expect(page.get_by_role("heading", name="Chez Carrefour", level=1)).to_be_visible()
    expect(page.get_by_role("checkbox")).to_have_count(4)


def test_follow_a_plan_tick_and_finish(mobile):
    page = mobile
    page.add_init_script(WAKE_LOCK)
    demo_list(page)
    compare(page)
    follow_carrefour(page)
    bar = page.get_by_test_id("trip-bar")
    expect(bar).to_contain_text("0/4")
    expect(bar).to_contain_text("sur 17,39 €")
    expect(bar.get_by_role("button", name="Terminer")).to_be_disabled()
    assert page.evaluate("() => window.__wake") >= 1  # the screen stays on
    expect(page.locator(".trip-row").filter(has_text="jus d'orange")).to_contain_text("6 × 1,45 €")
    assert_accessible(page, "en magasin")

    page.get_by_role("checkbox", name="beurre").check()
    expect(bar).to_contain_text("1/4 · 2,05 €")
    expect(page.locator("#live-region")).to_have_text("beurre pris, 1 sur 4")
    done = page.locator(".trip-aisle.done")
    expect(done.get_by_role("heading", name="Déjà pris (1)")).to_be_visible()
    expect(done.get_by_role("checkbox", name="beurre")).to_be_checked()
    assert wait_until(lambda: checked(page.base, "beurre"))
    page.reload()
    expect(page.get_by_role("checkbox", name="beurre")).to_be_checked()
    expect(bar).to_contain_text("1/4 · 2,05 €")

    bar.get_by_role("button", name="Terminer").click()
    sheet = page.get_by_role("dialog", name="Terminer les courses")
    expect(sheet).to_contain_text("1 article pris sur 4.")
    assert_accessible(page, "feuille « Terminer »")
    sheet.get_by_role("button", name="Retirer l'article pris de ma liste").click()
    toast = page.get_by_role("status")
    expect(toast).to_contain_text("1 article retiré de votre liste")
    expect(page.get_by_role("checkbox")).to_have_count(3)
    assert [i["query"] for i in call(page, "GET", "/api/list")] == ["sucre", "lessive", "jus d'orange"]
    toast.get_by_role("button", name="Annuler").click()
    expect(page.get_by_role("checkbox")).to_have_count(4)

    # « Tout décocher et garder la liste »
    bar.get_by_role("button", name="Terminer").click()
    page.get_by_role("dialog").get_by_role("button", name="Tout décocher et garder la liste").click()
    expect(page.get_by_role("status")).to_contain_text("Tous les articles sont décochés")
    expect(bar).to_contain_text("0/4")
    assert not any(i["checked"] for i in call(page, "GET", "/api/list"))


def test_ticks_without_network_are_kept_then_sent(mobile):
    page = mobile
    demo_list(page)
    compare(page)
    follow_carrefour(page)
    page.context.set_offline(True)
    page.get_by_role("checkbox", name="sucre").check()
    offline = page.get_by_text("Hors connexion : 1 coche sera envoyée au retour du réseau.")
    expect(offline).to_be_visible()
    expect(page.get_by_test_id("trip-bar")).to_contain_text("1/4 · 1,15 €")
    assert not checked(page.base, "sucre")

    page.context.set_offline(False)
    expect(offline).to_have_count(0, timeout=15000)
    assert wait_until(lambda: checked(page.base, "sucre"))
    page.reload()
    expect(page.get_by_role("checkbox", name="sucre")).to_be_checked()
    # The browser reports the requests refused while offline: expected here
    page.errors[:] = [e for e in page.errors if "ERR_INTERNET_DISCONNECTED" not in e]


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_one_hand_on_a_small_phone(chromium, server, scheme):
    from tests.e2e.conftest import open_page

    context, page = open_page(chromium, server, "mobile", color_scheme=scheme)
    try:
        page.set_viewport_size({"width": 360, "height": 740})
        demo_list(page)
        compare(page)
        follow_carrefour(page)
        for row in page.locator(".trip-check").all():
            assert row.bounding_box()["height"] >= 56
        box = page.locator(".trip-box").first.bounding_box()
        assert box["width"] >= 56 and box["height"] >= 56
        finish = page.get_by_role("button", name="Terminer")
        for _ in range(2):  # at the top, then at the bottom of the page: always under the thumb
            area = finish.bounding_box()
            assert area["height"] >= 44
            assert 740 - 140 <= area["y"] and area["y"] + area["height"] <= 740
            page.mouse.wheel(0, 2000)
        assert horizontal_overflow(page) == 0
        assert_accessible(page, f"en magasin ({scheme})")

        # A tap anywhere on the row ticks it
        page.get_by_text("Lessive liquide (2 L)").tap()
        expect(page.get_by_role("checkbox", name="lessive")).to_be_checked()
        expect(page.get_by_test_id("trip-bar")).to_contain_text("1/4 · 5,49 €")
    finally:
        context.close()
    assert page.errors == []


def test_two_retailers_of_a_plan(desktop):
    page = desktop
    call(page, "PATCH", "/api/basket/prefs", {"min_saving": 2})
    demo_list(page)
    plans = compare(page)["plans"]
    assert len(plans) == 2
    page.goto(f"{page.base}/#/courses?plan=1")
    sections = page.locator(".trip-store")
    expect(sections).to_have_count(2)
    lidl = sections.filter(has=page.locator(".badge", has_text="Lidl"))
    aldi = sections.filter(has=page.locator(".badge", has_text="Aldi"))
    for query in ("beurre", "sucre", "lessive"):
        expect(lidl.get_by_role("checkbox", name=query)).to_be_visible()
    expect(aldi.get_by_role("checkbox", name="jus d'orange (6 L)")).to_be_visible()
    expect(aldi).to_contain_text("0/1 · 6,90 €")
    expect(page.get_by_test_id("trip-bar")).to_contain_text("sur 14,67 €")
    call(page, "PATCH", "/api/basket/prefs", {"min_saving": 3})


def test_list_by_aisle_without_a_comparison(desktop):
    page = desktop
    demo_list(page)
    page.goto(f"{page.base}/#/courses")
    chooser = page.get_by_test_id("trip-chooser")
    expect(chooser).to_contain_text("Comparez d'abord votre panier")
    expect(chooser.get_by_role("button", name="Comparer mon panier")).to_be_visible()
    chooser.get_by_role("link", name=re.compile(r"^Ma liste par rayon")).click()
    expect(page.get_by_role("heading", name="Ma liste par rayon", level=1)).to_be_visible()
    for aisle in ("Crèmerie", "Épicerie sucrée", "Boissons", "Entretien"):
        expect(page.get_by_role("heading", name=aisle, level=3)).to_be_visible()
    expect(page.get_by_test_id("trip")).not_to_contain_text("€")
    expect(page.get_by_test_id("trip-bar")).to_contain_text("0/4")
    assert_accessible(page, "liste par rayon")

    # Back to the choice: the last trip can be resumed
    page.get_by_role("link", name="Changer de magasin").click()
    expect(page.get_by_role("link", name="Reprendre : Ma liste par rayon")).to_be_visible()


def test_the_list_changed_since_the_comparison(desktop):
    page = desktop
    demo_list(page)
    compare(page)
    call(page, "POST", "/api/list", {"query": "beurre"})  # 2 packs now
    page.goto(f"{page.base}/#/courses?plan=0")
    notice = page.get_by_text(
        "Votre liste a changé depuis la comparaison : produits et prix peuvent ne plus correspondre."
    )
    expect(notice).to_be_visible()
    page.get_by_role("button", name="Comparer à nouveau").click()
    expect(page).to_have_url(re.compile(r"#/panier$"))
    expect(page.get_by_test_id("basket-verdict")).to_contain_text("Panier le moins cher")


def test_printed_trip_is_a_checklist(desktop):
    page = desktop
    demo_list(page)
    compare(page)
    follow_carrefour(page)
    page.emulate_media(media="print")
    expect(page.get_by_role("button", name="Terminer")).to_be_hidden()
    expect(page.get_by_role("link", name="Changer de magasin")).to_be_hidden()
    box = page.locator(".trip-box").first.bounding_box()
    assert box["width"] < 30  # a small box to tick with a pen
