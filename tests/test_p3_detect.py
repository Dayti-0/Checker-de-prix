"""B48: anchored challenge detection, debug snapshots kept per retailer."""

import asyncio
import contextlib
import re
from datetime import datetime, timedelta

import pytest

from backend import config
from backend.browser import BrowserManager, BrowserUnavailable
from backend.scrapers import common
from backend.scrapers.common import classify_page, rotate_snapshots, save_debug_text, snapshot_path
from tests import fixtures
from tests.conftest import browser_missing


def test_challenge_title_needs_the_marks_of_a_challenge():
    shop = "https://www.aldi.fr/produits/un-instant-gourmand.html"
    # A product called « Un instant gourmand » is not a challenge
    assert classify_page(shop, "Un instant gourmand - ALDI") is None
    assert classify_page(shop, "Just a moment...") is None
    # Cloudflare: challenge elements, or the title with the marks of its pages
    assert classify_page(shop, "Just a moment...", cloudflare_marks=True) == "cloudflare"
    assert classify_page(shop, "Attention Required! | Cloudflare", cloudflare_marks=True) == "cloudflare"
    assert classify_page(shop, "Un instant…", cloudflare_marks=True) == "cloudflare"
    assert classify_page(shop, "Recherche", cloudflare_challenge=True) == "cloudflare"
    # The title must start with the words
    assert classify_page(shop, "Pause : un instant gourmand", cloudflare_marks=True) is None


def test_snapshot_path_is_timestamped(tmp_path):
    when = datetime(2026, 10, 3, 14, 5, 9)
    assert snapshot_path("aldi", "blocked", when) == tmp_path / "debug" / "aldi-20261003-140509-blocked.html"
    assert re.fullmatch(r"lidl-\d{8}-\d{6}-empty\.html", snapshot_path("lidl").name)


def test_only_the_last_five_snapshots_of_a_retailer_are_kept(tmp_path):
    debug = tmp_path / "debug"
    debug.mkdir()
    start = datetime(2026, 10, 3, 14, 0, 0)
    for i in range(8):
        path = snapshot_path("aldi", "empty" if i % 2 else "timeout", start + timedelta(seconds=i))
        path.write_text("x")
        path.with_suffix(".png").write_bytes(b"png")
    other = snapshot_path("aldi-test", "empty", start)  # another key that starts the same way
    other.write_text("x")
    rotate_snapshots("aldi")
    kept = sorted(p.name for p in debug.glob("aldi-2026*.html"))
    assert len(kept) == 5
    assert kept[0] == "aldi-20261003-140003-empty.html"
    assert len(list(debug.glob("aldi-2026*.png"))) == 5
    assert other.exists()


def test_raw_answer_kept_with_the_snapshots(tmp_path):
    path = save_debug_text("intermarche", "json", '{"erreur": "maintenance"}')
    assert path.parent == tmp_path / "debug"
    assert path.suffix == ".json" and "-json" in path.name
    assert path.read_text() == '{"erreur": "maintenance"}'


# --- detect_block in a real Chromium (fake pages) -------------------------------


@pytest.fixture(scope="module")
def manager(tmp_path_factory):
    m = BrowserManager(tmp_path_factory.mktemp("profile-detect"))
    try:
        asyncio.run(m.run("probe", _noop, timeout=60))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")
    yield m
    asyncio.run(m.shutdown())


async def _noop(page):
    return True


def _detect(manager, url, body, frames=None):
    async def scenario(page):
        await page.route("**/*", lambda route: route.abort())
        for frame_url, frame_body in (frames or {}).items():
            await page.route(frame_url + "**", _html(frame_body))
        await page.route(url, _html(body))
        await page.goto(url)
        return await common.detect_block(page)

    return asyncio.run(manager.run("detect", scenario, timeout=30))


def _html(body):
    return lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


def test_detect_block_on_pages(manager):
    url = "https://shop.example/"
    gourmand = "<html><head><title>Un instant gourmand</title></head><body>Gâteau</body></html>"
    assert _detect(manager, url, gourmand) is None
    challenge = (
        "<html><head><title>Just a moment...</title>"
        "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'></script></head><body></body></html>"
    )
    assert _detect(manager, url, challenge) == "cloudflare"
    frames = {"https://geo.captcha-delivery.com/": fixtures.DATADOME_CAPTCHA_FRAME}
    assert _detect(manager, url, fixtures.DATADOME_CAPTCHA_PAGE, frames) == "captcha"
    frames = {"https://geo.captcha-delivery.com/": fixtures.DATADOME_BLOCK_FRAME}
    assert _detect(manager, url, fixtures.DATADOME_BLOCK_PAGE, frames) == "hard_block"
    # Block text inside a captcha frame without t=bv: still a hard block
    assert _detect(manager, url, fixtures.DATADOME_CAPTCHA_PAGE, frames) == "hard_block"


def test_snapshot_on_a_real_page(manager, tmp_path):
    async def scenario(page):
        await page.route("**/*", lambda route: route.abort())
        await page.route("https://shop.example/", _html("<html><body>Rien</body></html>"))
        await page.goto("https://shop.example/")
        return await common.save_debug_snapshot(page, "shop", "empty")

    path = asyncio.run(manager.run("snapshot", scenario, timeout=30))
    assert path.parent == config.DEBUG_DIR
    assert "Rien" in path.read_text()
    assert path.with_suffix(".png").exists()


# --- B48: page kept when a search fails, source of the products ---------------------


def test_failed_search_keeps_the_page(manager, monkeypatch):
    from backend.scrapers import SCRAPERS

    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(common, "CHALLENGE_WAIT_SECONDS", 1)
    challenge = (
        "<html><head><title>Just a moment...</title></head>"
        "<body><div id='challenge-running'>Vérification</div></body></html>"
    )

    def routes(body=None):
        async def scenario(page):
            await page.unroute_all(behavior="ignoreErrors")
            await page.route("**/*", lambda route: route.abort())

            async def search_page(route):
                if body is None:
                    await asyncio.sleep(3)  # the site does not answer in time
                    with contextlib.suppress(Exception):
                        await route.abort()
                    return
                await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)

            await page.route(re.compile(r"https://www\.aldi\.fr/recherche\.html.*"), search_page)

        return scenario

    asyncio.run(manager.run("snap", routes(challenge), timeout=30))
    with pytest.raises(common.BlockedError):
        asyncio.run(manager.run("snap", SCRAPERS["aldi"].search, "farine", None, timeout=30))
    asyncio.run(manager.run("snap", routes(None), timeout=30))
    with pytest.raises(TimeoutError):
        asyncio.run(manager.run("snap", SCRAPERS["aldi"].search, "farine", None, timeout=2))
    names = sorted(p.name for p in config.DEBUG_DIR.glob("snap-*.html"))
    assert [n.rsplit("-", 1)[1] for n in names] == ["blocked.html", "timeout.html"]
    assert "challenge-running" in (config.DEBUG_DIR / names[0]).read_text()
    assert (config.DEBUG_DIR / names[0]).with_suffix(".png").exists()


def test_snapshot_status():
    from backend.browser import snapshot_status
    from backend.scrapers import SCRAPERS
    from backend.scrapers.base import HardBlockError, StoreRequiredError

    search = SCRAPERS["aldi"].search
    assert snapshot_status(search, common.BlockedError("x")) == "blocked"
    assert snapshot_status(search, HardBlockError("x")) == "blocked"
    assert snapshot_status(search, TimeoutError()) == "timeout"
    assert snapshot_status(search, ValueError("JSON")) == "error"
    assert snapshot_status(search, StoreRequiredError("x")) is None

    async def not_a_scraper(page):
        return None

    assert snapshot_status(not_a_scraper, TimeoutError()) is None


def test_source_is_kept_and_a_fallback_is_logged(monkeypatch, caplog):
    from backend.models import Product
    from backend.services import search
    from tests.conftest import run

    async def generic(scraper, query, store):
        scraper.last_source = "generic" if scraper.key == "lidl" else "api"
        return [Product(store=scraper.key, name="Farine", price=1.0)]

    monkeypatch.setattr(search, "_scrape", generic)
    with caplog.at_level("WARNING", logger="prixmalin.search"):
        lidl = run(search.search_store("lidl", "farine"))
        carrefour = run(search.search_store("carrefour", "farine"))
    assert (lidl.source, carrefour.source) == ("generic", "api")
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("Lidl" in w and "generic" in w for w in warnings)
    assert not any("Carrefour" in w for w in warnings)
