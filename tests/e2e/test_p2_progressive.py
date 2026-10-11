"""Progressive display of a search (B28): each retailer as soon as it answers, without jumps.

The fake retailers answer after ``fake.DELAYS`` seconds (changed here, put back after each test).
"""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e import fake
from tests.e2e.p2_helpers import choose_view, search, serve_thumbnails, wait_done

# Order in which the retailers answer (like the demo with --fixed)
STAGGERED = {"aldi": 0.3, "intermarche": 0.5, "lidl": 0.7, "coursesu": 0.9, "carrefour": 1.1}

LAYOUT_SHIFTS = """
window.__shifts = [];
new PerformanceObserver((list) => {
    for (const e of list.getEntries()) if (!e.hadRecentInput) window.__shifts.push(e.value);
}).observe({ type: "layout-shift", buffered: false });
"""


@pytest.fixture
def delays():
    saved = dict(fake.DELAYS)
    yield fake.DELAYS
    fake.DELAYS.clear()
    fake.DELAYS.update(saved)


def request_search(page, query):
    """A search asked without any input of the user (layout shifts all count)."""
    page.evaluate("async (q) => (await import('/static/js/core/store.js')).requestSearch(q)", query)


def test_focus_stays_when_another_retailer_answers(desktop, delays):
    page = desktop
    delays.update({"lidl": 0.8, "carrefour": 1.6})
    page.goto(page.base)
    search(page, "farine", wait=False)
    plus = page.get_by_role("button", name=re.compile(r"^Ajouter Farine de blé T55"))
    expect(plus).to_be_visible()
    plus.focus()
    handle = plus.element_handle()
    expect(page.locator(".column[data-store=carrefour] .product").first).to_be_visible()
    wait_done(page)
    # « Le moins cher » went to Lidl meanwhile: the button of Aldi is still the same, focused
    expect(page.locator(".column[data-store=lidl] .tag.best")).to_be_visible()
    assert page.evaluate("(el) => el.isConnected && document.activeElement === el", handle)


def test_a_new_search_cancels_the_previous_one(desktop, delays):
    page = desktop
    delays.update({"carrefour": 2.5})
    aborted = []
    page.on("requestfailed", lambda r: aborted.append(r.url) if "/api/search/" in r.url else None)
    page.goto(page.base)
    search(page, "farine", wait=False)
    expect(page.locator(".column[data-store=aldi] .product").first).to_be_visible()
    search(page, "vinaigre")
    assert any("/api/search/carrefour?q=farine" in url for url in aborted), aborted
    expect(page.locator("#results-body")).not_to_contain_text("Farine")


def test_busy_state_and_announcements(desktop, delays):
    page = desktop
    delays.update({"carrefour": 0.8})
    page.goto(page.base)
    search(page, "farine", wait=False)
    expect(page.locator("#results")).to_have_attribute("aria-busy", "true")
    live = page.locator("#live-region")
    expect(live).to_have_text("Recherche de « farine » dans 5 enseignes…")
    expect(page.locator(".summary-progress")).to_contain_text("enseignes ont répondu")
    wait_done(page)
    expect(live).to_have_text("Terminé : le moins cher est Lidl, 0,75 €, Farine de blé T45. 2 enseignes indisponibles.")
    expect(page.locator(".summary-foot")).to_have_text("5 enseignes comparées · 2 indisponibles")
    expect(page.locator("#updated")).to_have_text("Mis à jour à l'instant")


def test_usual_time_then_slow_retailer_can_be_ignored(desktop, delays):
    page = desktop
    delays.update({"carrefour": 6})
    page.clock.install()
    page.goto(page.base)
    page.evaluate("localStorage.setItem('prixmalin.durations', JSON.stringify({carrefour: [8000, 7000, 9000]}))")
    search(page, "farine", wait=False)
    line = page.locator("[data-summary=carrefour]")
    expect(line).to_contain_text("Recherche… ~8 s")
    expect(page.locator(".column[data-store=carrefour] .column-status")).to_contain_text("~8 s")
    page.clock.fast_forward("00:20")
    expect(line).to_contain_text("Plus long que d'habitude…")
    line.get_by_role("button", name="Ignorer Carrefour pour cette recherche").click()
    expect(page.get_by_test_id("unavailable").locator("[data-store=carrefour]")).to_contain_text("Ignorée cette fois")
    expect(line).to_contain_text("Ignorée cette fois")
    expect(page.locator("#results")).to_have_attribute("aria-busy", "false")
    # « Réessayer » asks it again
    page.get_by_role("button", name="Réessayer Carrefour").click()
    expect(line).to_contain_text("Recherche…")


@pytest.mark.parametrize("viewport", ["desktop", "mobile"])
def test_the_page_does_not_jump_while_retailers_answer(request, viewport, delays):
    """Cumulative layout shift under 0.1 on a search at 5 retailers."""
    page = request.getfixturevalue(viewport)
    delays.update(STAGGERED)
    page.goto(f"{page.base}/#/recherche?q=sel")
    wait_done(page)
    page.evaluate(LAYOUT_SHIFTS)
    request_search(page, "farine")
    wait_done(page)
    page.wait_for_timeout(300)
    shifts = page.evaluate("() => window.__shifts")
    assert sum(shifts) < 0.1, shifts


def test_thumbnails_are_asked_once(desktop, delays):
    page = desktop
    seen = []
    serve_thumbnails(page, seen)
    delays.update({"lidl": 0.4, "carrefour": 0.8})
    page.goto(page.base)
    search(page, "pois chiches")
    images = page.locator("#results-body .thumb img")
    expect(images).to_have_count(3)
    for i in range(3):
        img = images.nth(i)
        expect(img).to_have_attribute("loading", "lazy")
        expect(img).to_have_attribute("decoding", "async")
        expect(img).to_have_attribute("width", "56")
        expect(img).to_have_attribute("height", "56")
    page.wait_for_function("() => [...document.querySelectorAll('#results-body .thumb img')].every((i) => i.complete)")
    # Rows updated in place while the retailers answered: one request per thumbnail
    assert sorted(seen) == sorted(set(seen)) and len(seen) == 3, seen
    # Neither when the order changes (rows moved, not rebuilt). The other view
    # draws its own rows: their thumbnails are loaded first, then the sort changes.
    choose_view(page, "Tout trié")
    expect(images).to_have_count(3)
    page.wait_for_function("() => [...document.querySelectorAll('#results-body .thumb img')].every((i) => i.complete)")
    page.wait_for_timeout(300)
    del seen[:]
    page.get_by_role("radio", name="Pertinence").check()
    page.get_by_role("radio", name="Prix", exact=True).check()
    page.wait_for_timeout(300)
    assert seen == []


def test_a_broken_thumbnail_leaves_the_drawing(desktop):
    page = desktop
    page.route("https://images.prixmalin.test/**", lambda route: route.fulfill(status=404, body=""))
    page.goto(page.base)
    search(page, "pois chiches")
    expect(page.locator("#results-body .thumb img")).to_have_count(0)
    expect(page.locator(".column[data-store=aldi] .thumb svg")).to_be_visible()
    # The 404 of the images were reported by the browser on purpose
    page.errors[:] = [e for e in page.errors if "Failed to load resource" not in e]


def test_back_shows_the_previous_search_without_asking_again(desktop):
    page = desktop
    page.goto(page.base)
    search(page, "farine")
    search(page, "vinaigre")
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "/api/search" in r.url else None)
    page.go_back()
    expect(page).to_have_url(re.compile(r"#/recherche\?q=farine$"))
    expect(page.locator(".column[data-store=lidl]")).to_contain_text("Farine de blé T45")
    expect(page.get_by_role("searchbox", name="Produit à rechercher")).to_have_value("farine")
    page.go_forward()
    expect(page.locator(".column[data-store=aldi]")).to_contain_text("Vinaigre de cidre bio")
    assert asked == []


def test_the_keyboard_of_a_phone_closes_after_a_search(mobile):
    page = mobile
    page.goto(page.base)
    box = page.get_by_role("searchbox", name="Produit à rechercher")
    box.fill("farine")
    box.press("Enter")
    wait_done(page)
    expect(box).not_to_be_focused()


def test_new_offers_wait_while_the_user_reads_further_down(mobile, delays):
    page = mobile
    delays.update({"carrefour": 2.5})
    page.goto(page.base)
    search(page, "huile de tournesols", wait=False)
    rows = page.locator("[data-testid=offers] .offer-list .product")
    expect(rows).to_have_count(4)  # Aldi and Lidl
    # The user reads the list further down: the offers of Carrefour wait
    page.mouse.wheel(0, 600)
    page.wait_for_function("() => window.scrollY > 300")
    wait_done(page)
    banner = page.get_by_test_id("new-offers")
    expect(banner).to_have_text("2 nouvelles offres")
    expect(rows).to_have_count(4)
    # The summary already counts them
    expect(page.locator("[data-summary=carrefour]")).to_contain_text("1,95 €")
    banner.click()
    expect(rows).to_have_count(6)
    expect(banner).to_have_count(0)


def test_prices_of_a_while_ago_and_old_prices(desktop, monkeypatch):
    """« prix d'il y a 2 h » from the cache; « Prix du … » when the site fails (last prices kept)."""
    import sqlite3

    from backend import config
    from backend.scrapers.base import BlockedError
    from backend.services import search as search_service

    page = desktop
    assert page.request.get(f"{page.base}/api/search", params={"q": "farine", "stores": "aldi,lidl"}).ok
    with sqlite3.connect(config.DB_PATH) as db:
        db.execute("UPDATE search_cache SET created_at = created_at - 7200 WHERE cache_key LIKE 'aldi|%'")
    db.close()
    page.goto(page.base)
    search(page, "farine")
    aldi = page.locator(".column[data-store=aldi]")
    expect(aldi.locator(".column-head .column-status")).to_have_text("2 produits · prix d'il y a 2 h")
    expect(page.locator("#updated")).to_have_text("Mis à jour il y a 2 h")

    # The site of Aldi asks for a check: its last prices stay, marked as old
    fake_scrape = search_service._scrape

    async def blocked(scraper, query, store):
        if scraper.key == "aldi":
            raise BlockedError("Aldi affiche une vérification anti-robot.")
        return await fake_scrape(scraper, query, store)

    monkeypatch.setattr(search_service, "_scrape", blocked)
    page.get_by_role("button", name="Actualiser les prix").click()
    wait_done(page)
    notice = aldi.locator(".notice.warn")
    expect(notice).to_contain_text(re.compile(r"Prix du \d\d/\d\d à \d+ h.*\(Aldi : vérification requise\)"))
    expect(notice.get_by_role("button", name="Ouvrir le site Aldi")).to_be_visible()
    expect(aldi.locator(".product")).to_have_count(2)
    expect(page.locator("[data-summary=aldi]")).to_contain_text("ancien prix")
