"""B42, B43, B50: shared browser closed by the user, protected start, light tabs, user agent kept."""

import asyncio
import contextlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.browser import PROFILE_IN_USE, BrowserManager, BrowserUnavailable, is_light_blocked, is_profile_locked
from backend.repos import cache
from backend.services import settings as settings_service
from tests.conftest import browser_missing, run
from tests.p3_chrome import display


async def _url(page):
    return page.url


def start(manager, key="probe", timeout=60):
    try:
        return asyncio.run(manager.run(key, _url, timeout=timeout))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)


@pytest.fixture(scope="module")
def screen():
    with display() as available:
        if not available:
            browser_missing("pas d'écran pour la fenêtre visible (installez Xvfb)")
        yield


# --- B42: window closed by the user -------------------------------------------------


def test_window_closed_by_the_user(screen, tmp_path):
    manager = BrowserManager(tmp_path / "profile", persist=True)

    async def scenario():
        await settings_service.set_show_browser(True)
        await cache.set_cached("aldi|||farine", [])
        await cache.set_cached("lidl|||farine", [])
        manager.show_browser = True
        await manager.open_setup("aldi", "data:text/html,<p>Aldi</p>")
        status = manager.status()
        assert (status.setup_mode, status.setup_store, status.headless) == (True, "aldi", False)
        generation = manager.context_generation

        async def close_window(page):
            session = await page.context.new_cdp_session(page)
            # What closing the window does (the browser may go away while answering)
            with contextlib.suppress(Exception):
                await session.send("Browser.close")

        await manager.run("aldi", close_window, timeout=20)
        for _ in range(100):
            if not manager.status().running:
                break
            await asyncio.sleep(0.05)
        closed = manager.status()
        assert closed.running is False and closed.closed_by_user is True
        assert (closed.setup_mode, closed.setup_store) == (False, None)
        assert manager.show_browser is False
        assert manager.context_generation == generation + 1

        # The next search starts the invisible browser again
        await manager.run("aldi", _url, timeout=60)
        again = manager.status()
        assert again.running and again.headless and not again.setup_mode
        saved = await settings_service.load_settings()
        assert saved.show_browser is False
        # Only the results of the retailer that was open are forgotten
        assert await cache.get_entry("aldi|||farine") is None
        assert await cache.get_entry("lidl|||farine") is not None
        await manager.shutdown()

    run(scenario())


def test_switching_the_window_during_a_search_does_not_break_it(screen, tmp_path):
    manager = BrowserManager(tmp_path / "profile")
    start(manager)

    async def slow(page):
        await asyncio.sleep(1.5)
        return "fini"

    async def scenario():
        search = asyncio.create_task(manager.run("aldi", slow, timeout=30))
        await asyncio.sleep(0.3)
        await manager.set_show_browser(True)  # waits for the search, then shows the window
        result = await search
        visible = manager.status().headless is False
        await manager.set_show_browser(False)
        return result, visible

    result, visible = asyncio.run(scenario())
    assert result == "fini" and visible
    assert manager.status().headless is True
    asyncio.run(manager.shutdown())


# --- B43: protected start ------------------------------------------------------------


def test_a_search_that_gives_up_does_not_stop_the_start(tmp_path):
    manager = BrowserManager(tmp_path / "profile")
    try:
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(manager.run("aldi", _url, timeout=0.8))
        assert asyncio.run(manager.run("aldi", _url, timeout=60)) == "about:blank"
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")
    assert manager.launch_count <= 2  # one start (plus the user agent fix on the first one)
    assert manager.context_generation == 1
    asyncio.run(manager.shutdown())


def test_profile_in_use_is_said_in_french_with_one_try(tmp_path, monkeypatch):
    manager = BrowserManager(tmp_path / "profile")
    tried = []

    async def locked(channel, headless, **kwargs):
        tried.append(channel)
        raise RuntimeError(
            "BrowserType.launch_persistent_context: Failed to create a ProcessSingleton for your profile directory."
        )

    monkeypatch.setattr(manager, "_launch_channel", locked)
    with pytest.raises(BrowserUnavailable) as error:
        asyncio.run(manager.run("aldi", _url, timeout=30))
    assert str(error.value) == PROFILE_IN_USE
    assert len(tried) == 1  # no other browser tried
    assert manager.status().error == PROFILE_IN_USE
    asyncio.run(manager.shutdown())


def test_profile_lock_messages():
    assert is_profile_locked("Failed to create a ProcessSingleton for your profile directory")
    assert is_profile_locked("The profile appears to be in use by another Chromium process")
    assert not is_profile_locked("Executable doesn't exist at /ms-playwright/chromium")


def test_half_launched_browser_is_closed(tmp_path, monkeypatch):
    manager = BrowserManager(tmp_path / "profile")
    failures = []

    async def broken_stealth(context):
        failures.append(context)
        raise RuntimeError("stealth failed badly")

    monkeypatch.setattr(manager, "_apply_stealth", broken_stealth)
    with pytest.raises(BrowserUnavailable):
        asyncio.run(manager.run("aldi", _url, timeout=60))
    if not failures:
        browser_missing("Chromium unavailable")
    assert all(not context.pages for context in failures)  # every half-launched browser was closed
    monkeypatch.undo()
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    # The profile is free: the next start works
    assert asyncio.run(manager.run("aldi", _url, timeout=60)) == "about:blank"
    asyncio.run(manager.shutdown())


# --- B50: light tabs, remembered user agent --------------------------------------------


def test_light_requests():
    assert is_light_blocked("image", "https://www.aldi.fr/img/farine.jpg")
    assert is_light_blocked("font", "https://www.aldi.fr/f.woff2")
    assert is_light_blocked("script", "https://securepubads.g.doubleclick.net/tag/js/gpt.js")
    assert not is_light_blocked("script", "https://www.aldi.fr/app.js")
    assert not is_light_blocked("document", "https://www.aldi.fr/recherche.html?query=farine")


def _light_scenario(page_body):
    async def scenario(page):
        failed, served = [], []
        page.on("requestfailed", lambda r: failed.append((r.url, r.failure)))
        # Last resort after the routes of the tab: nothing leaves the browser
        await page.context.route("**/*", lambda route: route.abort())

        async def handler(route):
            url = route.request.url
            if url.startswith("https://www.aldi.fr/recherche"):
                await route.fulfill(status=200, content_type="text/html", body=page_body)
            elif url.endswith(".png"):
                served.append(url)
                await route.fallback()  # the light route of the tab decides
            else:
                await route.abort()

        await page.route("**/*", handler)
        await page.goto("https://www.aldi.fr/recherche.html?query=farine")
        await page.wait_for_timeout(300)
        return failed

    return scenario


def test_images_are_not_loaded_by_the_invisible_aldi_tab(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIGHT_MODE", True)
    manager = BrowserManager(tmp_path / "profile")
    body = "<html><body><img src='https://www.aldi.fr/img/farine.png'></body></html>"
    try:
        failed = asyncio.run(manager.run("aldi", _light_scenario(body), timeout=60))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")
    assert [u for u, failure in failed if failure.startswith("net::ERR_BLOCKED_BY_CLIENT")] == [
        "https://www.aldi.fr/img/farine.png"
    ]
    # Carrefour (Cloudflare) loads everything
    failed = asyncio.run(manager.run("carrefour", _light_scenario(body), timeout=60))
    assert not any(failure.startswith("net::ERR_BLOCKED_BY_CLIENT") for _, failure in failed)
    asyncio.run(manager.shutdown())


def test_light_mode_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIGHT_MODE", False)
    manager = BrowserManager(tmp_path / "profile")
    body = "<html><body><img src='https://www.aldi.fr/img/farine.png'></body></html>"
    try:
        failed = asyncio.run(manager.run("aldi", _light_scenario(body), timeout=60))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")
    assert not any(failure.startswith("net::ERR_BLOCKED_BY_CLIENT") for _, failure in failed)
    asyncio.run(manager.shutdown())


def test_user_agent_is_remembered_for_the_next_start(tmp_path):
    first = BrowserManager(tmp_path / "profile")
    start(first)
    memo = json.loads((tmp_path / "browser-ua.json").read_text())
    channel = first.status().channel
    assert "HeadlessChrome" not in memo[channel]["user_agent"]
    assert memo[channel]["version"]
    asyncio.run(first.shutdown())

    second = BrowserManager(tmp_path / "profile")
    start(second)

    async def user_agent(page):
        return await page.evaluate("navigator.userAgent")

    assert second.launch_count == 1  # started once
    assert asyncio.run(second.run("probe", user_agent, timeout=10)) == memo[channel]["user_agent"]
    asyncio.run(second.shutdown())


# --- « Réessayer maintenant » after a hard block ----------------------------------------


def test_lifting_a_pause_keeps_its_doubling():
    from backend.services.circuit import HardBlocks

    async def scenario():
        blocks = HardBlocks(persist=True)
        first = await blocks.hard_block("intermarche")
        await blocks.lift("intermarche")
        assert await blocks.until("intermarche") is None
        second = await blocks.hard_block("intermarche")
        return first, second

    first, second = run(scenario())
    assert second.seconds == 2 * first.seconds


def test_unblock_api(monkeypatch):
    from backend import main
    from backend.browser import browser

    async def never(*args, **kwargs):
        raise AssertionError("no visit")

    monkeypatch.setattr(browser, "run", never)
    with TestClient(main.app) as client:
        client.portal.call(browser.hard_blocks.hard_block, "intermarche")
        status = client.get("/api/browser").json()
        assert status["blocked_until"]["intermarche"] > time.time()
        window = next(w for w in status["windows"] if w["store"] == "intermarche")
        assert window["label"] == "Intermarché"
        after = client.delete("/api/browser/blocks/intermarche").json()
        assert after["blocked_until"] == {}
        assert client.delete("/api/browser/blocks/inconnue").status_code == 404
