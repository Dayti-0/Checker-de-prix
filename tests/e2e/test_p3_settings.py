"""Réglages › Navigateur (P3): visible window switch, Intermarché window, troubleshooting."""

import re
import time

import pytest
from playwright.sync_api import expect

from backend import config
from backend.browser import browser
from backend.models import BlockRecord
from tests.e2e import fake
from tests.e2e.axe import assert_accessible
from tests.e2e.helpers import js_eval

ADVANCED = "/static/js/views/settings/sections/advanced.js"


@pytest.fixture(params=["desktop", "dark", "mobile"])
def page(request):
    return request.getfixturevalue(request.param)


@pytest.fixture
def paused():
    """Intermarché paused after a hard block, for one hour."""
    blocks = browser.hard_blocks
    until = time.time() + 3600
    blocks._loaded_from = str(config.DB_PATH)
    blocks._records["intermarche"] = BlockRecord(until=until, seconds=1800, last_hard_block=time.time())
    yield until
    blocks._records.pop("intermarche", None)


def section(page):
    return page.locator("[data-section=advanced]")


def test_browser_section(page):
    page.goto(f"{page.base}/#/reglages")
    advanced = section(page)
    expect(advanced.get_by_role("heading", name="Navigateur")).to_be_visible()
    switch = advanced.get_by_role("checkbox", name=re.compile("Montrer le navigateur de PrixMalin"))
    expect(switch).not_to_be_checked()
    expect(advanced.get_by_test_id("browser-status")).to_have_text("Le navigateur démarrera à la première recherche.")
    window = advanced.locator("[data-window=intermarche]")
    expect(window).to_contain_text("Intermarché utilise une fenêtre Chrome à part")
    expect(window.locator("[data-window-status]")).to_have_text(
        "La fenêtre d'Intermarché s'ouvrira, réduite, à la prochaine recherche Intermarché."
    )

    # Troubleshooting: one button per retailer, folded at first
    open_itm = advanced.get_by_role("button", name="Ouvrir Intermarché (fenêtre Chrome)")
    expect(open_itm).to_be_hidden()
    advanced.get_by_text("Dépannage").click()
    expect(open_itm).to_be_visible()
    for label in ("Aldi", "Lidl", "Carrefour", "Courses U"):
        expect(advanced.get_by_role("button", name=f"Ouvrir {label}", exact=True)).to_be_visible()
    expect(advanced.get_by_role("link", name="État des enseignes")).to_have_attribute("href", "#/etat")
    assert_accessible(page, "réglages navigateur")
    no_scroll = "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    assert page.evaluate(no_scroll)

    open_itm.click()
    expect(page.locator("#setup-banner")).to_be_visible()
    assert fake.state.opened == ["intermarche"]

    switch.check()
    expect(advanced.get_by_test_id("browser-status")).not_to_be_empty()
    page.reload()
    expect(section(page).get_by_role("checkbox", name=re.compile("Montrer le navigateur"))).to_be_checked()
    section(page).get_by_role("checkbox", name=re.compile("Montrer le navigateur")).uncheck()


def test_hard_block_pause_can_be_lifted(desktop, paused):
    page = desktop
    page.goto(f"{page.base}/#/reglages")
    window = section(page).locator("[data-window=intermarche]")
    clock = js_eval(page, ADVANCED, "clockText", paused)
    expect(window.locator("[data-window-status]")).to_have_text(
        f"Intermarché bloque temporairement cette connexion : PrixMalin ne le contactera pas avant {clock}."
    )
    assert_accessible(page, "pause Intermarché")
    page.once("dialog", lambda dialog: dialog.accept())
    window.get_by_role("button", name="Réessayer Intermarché maintenant").click()
    expect(page.locator("#toast")).to_have_text("Intermarché sera de nouveau consulté à la prochaine recherche.")
    expect(window.get_by_role("button", name="Réessayer Intermarché maintenant")).to_have_count(0)
    assert browser.hard_blocks.active() == {}


def test_hard_block_pause_kept_when_the_user_says_no(desktop, paused):
    page = desktop
    page.goto(f"{page.base}/#/reglages")
    page.once("dialog", lambda dialog: dialog.dismiss())
    section(page).get_by_role("button", name="Réessayer Intermarché maintenant").click()
    expect(section(page).get_by_role("button", name="Réessayer Intermarché maintenant")).to_be_visible()
    assert "intermarche" in browser.hard_blocks.active()


def test_state_texts(desktop):
    page = desktop
    page.goto(page.base)
    now = js_eval(page, ADVANCED, "clockText", 0, 0)  # same day as itself
    assert re.fullmatch(r"\d{1,2} h \d{2}", now)
    noon = page.evaluate("() => new Date(2026, 9, 3, 12, 0).getTime()")
    assert js_eval(page, ADVANCED, "clockText", (noon + 3_000_000) / 1000, noon) == "12 h 50"
    assert js_eval(page, ADVANCED, "clockText", (noon + 86_400_000) / 1000, noon) == "demain à 12 h 00"
    assert js_eval(page, ADVANCED, "clockText", (noon + 3 * 86_400_000) / 1000, noon) == "le 06/10 à 12 h 00"
    window = {"store": "intermarche", "label": "Intermarché", "running": True, "browser": "Google Chrome"}
    assert js_eval(page, ADVANCED, "windowText", window, None) == "La fenêtre Google Chrome d'Intermarché est ouverte."
    closed = {**window, "running": False, "closed_by_user": True}
    assert "elle se rouvrira, réduite" in js_eval(page, ADVANCED, "windowText", closed, None)
    assert js_eval(page, ADVANCED, "of", "Lidl") == "de Lidl"
    shared = {"running": True, "headless": True, "channel": "chrome"}
    assert js_eval(page, ADVANCED, "browserText", shared) == "Navigateur actif (Google Chrome, sans fenêtre)."
    assert "les recherches continuent sans fenêtre" in js_eval(
        page, ADVANCED, "browserText", {"running": False, "closed_by_user": True}
    )


@pytest.mark.parametrize("width", [360, 390])
@pytest.mark.parametrize("scale", [0.9, 1.6])
def test_no_horizontal_scroll_on_a_phone(mobile, paused, width, scale):
    page = mobile
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(page.base)
    page.evaluate(f"() => localStorage.setItem('prixmalin.textScale', '{scale}')")
    page.goto(f"{page.base}/#/reglages")
    advanced = section(page)
    advanced.get_by_text("Dépannage").click()
    expect(advanced.get_by_role("button", name="Ouvrir Intermarché (fenêtre Chrome)")).to_be_visible()
    expect(advanced.get_by_role("button", name="Réessayer Intermarché maintenant")).to_be_visible()
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0
    page.evaluate("() => localStorage.removeItem('prixmalin.textScale')")


@pytest.mark.parametrize("scale", [0.9, 1])
def test_finger_sized_targets(mobile, paused, scale):
    """Every target of the section measures at least 44x44 px, at the smallest text size too."""
    page = mobile
    page.goto(page.base)
    page.evaluate(f"() => localStorage.setItem('prixmalin.textScale', '{scale}')")
    page.goto(f"{page.base}/#/reglages")
    advanced = section(page)
    advanced.get_by_text("Dépannage").click()
    expect(advanced.get_by_role("button", name="Réessayer Intermarché maintenant")).to_be_visible()
    sizes = advanced.evaluate(
        """el => [...el.querySelectorAll('button, summary, a, label.switch')].map(t => {
            const r = t.getBoundingClientRect();
            return [t.textContent.trim().slice(0, 30), Math.round(r.width), Math.round(r.height)];
        })"""
    )
    assert len(sizes) >= 9  # switch, summary, 5 « Ouvrir », « Réessayer », link
    small = [s for s in sizes if s[1] < 44 or s[2] < 44]
    assert small == []
    page.evaluate("() => localStorage.removeItem('prixmalin.textScale')")
