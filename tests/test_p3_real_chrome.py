"""B41: the dedicated real Chrome window of Intermarché (backend/real_chrome.py).

Pure functions first (where Chrome is found, command line, port file), then
scenarios in a real visible Chromium driven like the user's Chrome: the
fake intermarche.com pages and API answers of tests/fixtures/intermarche.py
are served by request interception, nothing leaves the machine.
"""

import asyncio
import json
import re
import time
from pathlib import Path

import pytest

from backend import config
from backend.browser import BrowserManager, BrowserUnavailable
from backend.models import StoreSelection
from backend.real_chrome import (
    CHROME_MISSING,
    PORT_FILE,
    chrome_candidates,
    find_chrome,
    launch_args,
    name_from_user_agent,
    on_site,
    parse_port_file,
)
from backend.scrapers import SCRAPERS, common
from backend.scrapers.base import BlockedError, HardBlockError, StoreRequiredError
from tests import fixtures
from tests.conftest import browser_missing
from tests.p3_chrome import dedicated_manager, sandbox_args

HOME = "https://www.intermarche.com/"

# --- pure functions -------------------------------------------------------------


def test_chrome_is_looked_for_where_windows_installs_it():
    env = {
        "ProgramFiles": r"C:\Program Files",
        "ProgramFiles(x86)": r"C:\Program Files (x86)",
        "LOCALAPPDATA": r"C:\Users\Paul\AppData\Local",
    }
    paths = [path for path, _ in chrome_candidates("win32", env)]
    assert paths[:3] == [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Users\Paul\AppData\Local\Google\Chrome\Application\chrome.exe",
    ]
    assert paths[3:] == [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]


def test_find_chrome_prefers_chrome_then_edge():
    env = {"ProgramFiles": r"C:\PF", "ProgramFiles(x86)": r"C:\PF86", "LOCALAPPDATA": r"C:\Local"}
    local_chrome = r"C:\Local\Google\Chrome\Application\chrome.exe"
    edge = r"C:\PF86\Microsoft\Edge\Application\msedge.exe"
    found = find_chrome(platform="win32", env=env, exists=lambda p: p in (local_chrome, edge))
    assert found == (local_chrome, "Google Chrome")
    found = find_chrome(platform="win32", env=env, exists=lambda p: p == edge)
    assert found == (edge, "Microsoft Edge")


def test_find_chrome_with_a_configured_path():
    assert find_chrome("/opt/chrome/chrome", platform="linux", exists=lambda p: True) == (
        "/opt/chrome/chrome",
        "Google Chrome",
    )
    # A wrong PRIXMALIN_CHROME_PATH is not replaced by another browser
    assert find_chrome("/nowhere/chrome", platform="linux", exists=lambda p: False) is None
    assert find_chrome(platform="linux", env={}, which=lambda name: None) is None
    assert find_chrome(platform="linux", env={}, which=lambda name: "/usr/bin/" + name)[1] == "Google Chrome"


def test_command_line_is_the_one_of_a_person_s_chrome(tmp_path):
    args = launch_args("chrome.exe", tmp_path / "chrome-intermarche", 9333, minimized=True)
    assert args == [
        "chrome.exe",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=9333",
        f"--user-data-dir={tmp_path / 'chrome-intermarche'}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-minimized",
        "about:blank",
    ]
    visible = launch_args("chrome.exe", tmp_path, 9333, minimized=False)
    assert "--start-minimized" not in visible
    joined = " ".join(args)
    for flag in ("headless", "enable-automation", "disable-blink-features", "--lang", "user-agent", "no-sandbox"):
        assert flag not in joined
    # Port 0 would make Chrome set navigator.webdriver to true
    assert "--remote-debugging-port=0" not in joined


def test_port_file():
    assert parse_port_file("9333\n") == 9333
    assert parse_port_file("41235\n/devtools/browser/0b5c\n") == 41235  # DevToolsActivePort of Chrome
    for text in ("", "abc", "0", "70000", "\n"):
        assert parse_port_file(text) is None


def test_on_site_and_browser_names():
    assert on_site("https://www.intermarche.com/recherche/farine", "intermarche.com")
    assert on_site("https://intermarche.com/", "intermarche.com")
    assert not on_site("https://geo.captcha-delivery.com/captcha/", "intermarche.com")
    assert not on_site("about:blank", "intermarche.com")
    assert not on_site("https://intermarche.com.evil.example/", "intermarche.com")
    assert name_from_user_agent("Mozilla/5.0 ... Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0") == "Microsoft Edge"
    assert name_from_user_agent("Mozilla/5.0 ... Chrome/141.0.0.0 Safari/537.36") == "Google Chrome"


def test_kill_switch_parsing():
    assert config.parse_store_list("intermarche") == ("intermarche",)
    assert config.parse_store_list(" Intermarche , carrefour ") == ("intermarche", "carrefour")
    assert config.parse_store_list("") == ()


def test_no_chrome_installed_is_said_in_french(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROME_PATH", str(tmp_path / "absent" / "chrome.exe"))
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche",))
    manager = BrowserManager(tmp_path / "profile", real_chrome_dir=tmp_path)

    async def never(page):
        raise AssertionError("no page without Chrome")

    with pytest.raises(BrowserUnavailable) as error:
        asyncio.run(manager.run("intermarche", never, timeout=20))
    assert str(error.value) == CHROME_MISSING
    status = manager.status()
    assert status.running is False  # the shared browser was not started for Intermarché
    assert status.windows[0].error == CHROME_MISSING
    asyncio.run(manager.shutdown())


# --- scenarios in a real visible Chromium -----------------------------------------


@pytest.fixture(scope="module")
def itm(tmp_path_factory):
    """A BrowserManager whose Intermarché tab is a dedicated visible Chromium."""
    with dedicated_manager(tmp_path_factory.mktemp("itm")) as manager:
        yield manager


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(config, "REQUEST_INTERVAL_SECONDS", {})
    monkeypatch.setattr(config, "REAL_CHROME_SETTLE_SECONDS", 0.3)
    monkeypatch.setattr(common, "CHALLENGE_WAIT_SECONDS", 1)


async def _blank(page):
    await page.unroute_all(behavior="ignoreErrors")
    if page.url != "about:blank":
        await page.goto("about:blank")
    return page.url


def html(body):
    return lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


def as_json(data, status=200):
    return lambda route: route.fulfill(status=status, content_type="application/json", body=json.dumps(data))


async def fresh(page, home=fixtures.INTERMARCHE_HOME_PAGE % "localStorage.clear();"):
    """A blank tab where nothing leaves the browser and intermarche.com is the fake site."""
    await _blank(page)
    await page.route("**/*", lambda route: route.abort())
    await page.route(HOME, html(home))


def run(manager, fn, key="intermarche", timeout=60):
    return asyncio.run(manager.run(key, fn, timeout=timeout))


def clear_blocks(manager):
    asyncio.run(manager.hard_blocks.clear("intermarche"))


def test_search_with_the_configured_store(itm):
    seen = {}

    async def scenario(page):
        await fresh(page)

        async def api(route, request):
            seen.update(url=request.url, headers=request.headers, body=json.loads(request.post_data))
            await route.fulfill(
                status=200, content_type="application/json", body=json.dumps(fixtures.INTERMARCHE_SEARCH)
            )

        await page.route("https://www.intermarche.com/api/service/produits/**", api)
        return await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))

    products = run(itm, scenario)
    assert [p.name for p in products] == ["Farine de blé T45", "Farine de sarrasin bio"]
    assert products[0].ean == "3250390018575"
    assert "/pdvs/06814/products/byKeywordAndCategory" in seen["url"]
    assert seen["headers"]["x-itm-device-fp"] == "dev-1"
    assert seen["headers"]["x-itm-session-id"] == "sess-1"
    assert seen["body"]["keyword"] == "farine"
    # Only the dedicated window was used: the shared browser was never started
    assert itm.status().running is False
    assert itm.status().windows[0].running is True


def test_store_chosen_on_the_site_and_escaped(itm):
    seen = {}

    async def scenario(page):
        await fresh(page, fixtures.INTERMARCHE_HOME_PAGE % "localStorage.setItem('itm-store', '08012');")

        async def api(route, request):
            seen["url"] = request.url
            await route.fulfill(status=200, content_type="application/json", body=json.dumps({"produits": []}))

        await page.route("https://www.intermarche.com/api/service/produits/**", api)
        first = await SCRAPERS["intermarche"].search(page, "farine", None)
        await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="12/34"))
        return first

    assert run(itm, scenario) == []
    assert "/pdvs/12%2F34/" in seen["url"]


def test_store_required(itm):
    async def scenario(page):
        await fresh(page)
        return await SCRAPERS["intermarche"].search(page, "farine", None)

    with pytest.raises(StoreRequiredError):
        run(itm, scenario)


def test_pause_after_the_first_load_only(itm, monkeypatch):
    monkeypatch.setattr(config, "REAL_CHROME_SETTLE_SECONDS", 1.5)
    calls = []

    async def scenario(page):
        await fresh(page)

        async def api(route, request):
            calls.append(time.monotonic())
            await route.fulfill(status=200, content_type="application/json", body=json.dumps({"produits": []}))

        await page.route("https://www.intermarche.com/api/service/produits/**", api)
        start = time.monotonic()
        await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))
        await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))
        return start

    start = run(itm, scenario)
    assert calls[0] - start >= 1.5  # the site's own scripts run before the first API call
    assert calls[1] - calls[0] < 1.0  # the tab is already on the site: no new load, no pause


def test_datadome_captcha_from_the_api(itm):
    clear_blocks(itm)

    async def scenario(page):
        await fresh(page)
        await page.route("https://www.intermarche.com/api/**", as_json(fixtures.DATADOME_CAPTCHA_JSON, 403))
        return await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))

    with pytest.raises(BlockedError) as error:
        run(itm, scenario)
    assert not isinstance(error.value, HardBlockError)
    assert "Ouvrir le site" in str(error.value)
    # « Ouvrir le site » will load the page again so that the check shows
    assert itm._real["intermarche"].challenge_pending is True
    assert itm.hard_blocks.record("intermarche").last_blocked > 0
    assert itm.hard_blocks.active() == {}


def test_datadome_captcha_shown_in_the_tab_is_reported_without_reloading(itm):
    loads = []

    async def scenario(page):
        await fresh(page)
        await page.route("https://geo.captcha-delivery.com/**", html(fixtures.DATADOME_CAPTCHA_FRAME))

        async def home(route):
            loads.append(route.request.url)
            await route.fulfill(status=200, content_type="text/html", body=fixtures.DATADOME_CAPTCHA_PAGE)

        await page.route(HOME, home)
        try:
            await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))
        except BlockedError as e:
            first = e
        else:
            raise AssertionError("captcha not seen")
        # The tab still shows the check: the next search says so at once
        with pytest.raises(BlockedError):
            await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))
        return first

    error = run(itm, scenario)
    assert not isinstance(error, HardBlockError)
    assert loads == [HOME]


def test_hard_block_stops_every_call(itm):
    clear_blocks(itm)
    calls = []

    async def scenario(page):
        await fresh(page)

        async def api(route):
            calls.append(route.request.url)
            await route.fulfill(
                status=403, content_type="application/json", body=json.dumps(fixtures.DATADOME_BLOCK_JSON)
            )

        await page.route("https://www.intermarche.com/api/**", api)
        return await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))

    with pytest.raises(HardBlockError) as error:
        run(itm, scenario)
    until = error.value.retry_after
    assert until is not None and 29 * 60 < until - time.time() <= 30 * 60
    assert "ne réessaiera pas avant" in str(error.value)
    assert len(calls) == 1  # never retried

    async def must_not_run(page):
        raise AssertionError("the site was called during the pause")

    for _ in range(3):
        with pytest.raises(HardBlockError) as again:
            run(itm, must_not_run)
        assert again.value.retry_after == until
    assert itm.status().blocked_until == {"intermarche": until}
    # « Ouvrir le site » is refused too: the window would only load the site again
    with pytest.raises(HardBlockError):
        asyncio.run(itm.open_setup("intermarche", HOME))
    clear_blocks(itm)


def test_hard_block_page_in_the_tab(itm):
    clear_blocks(itm)

    async def scenario(page):
        await fresh(page)
        await page.route("https://geo.captcha-delivery.com/**", html(fixtures.DATADOME_BLOCK_FRAME))
        await page.route(HOME, html(fixtures.DATADOME_BLOCK_PAGE))
        return await SCRAPERS["intermarche"].search(page, "farine", StoreSelection(id="06814"))

    start = time.monotonic()
    with pytest.raises(HardBlockError):
        run(itm, scenario)
    assert time.monotonic() - start < 5  # no wait for a check that would pass by itself
    assert "intermarche" in itm.hard_blocks.active()
    clear_blocks(itm)


def test_open_waiting_behind_a_hard_block_loads_nothing(itm):
    """« Ouvrir le site » asked while a search is refused: no page of the site is loaded."""
    clear_blocks(itm)
    loads = []

    async def prepare(page):
        await fresh(page)
        await page.goto("about:blank")

    run(itm, prepare)

    async def refused(page):
        await page.route(HOME, lambda route: (loads.append(route.request.url), route.abort())[1])
        await asyncio.sleep(0.5)  # the API answers 403 t=bv after a while
        raise HardBlockError("bloqué", label="Intermarché")

    async def scenario():
        search = asyncio.create_task(itm.run("intermarche", refused, timeout=30))
        await asyncio.sleep(0.2)
        with pytest.raises(HardBlockError) as opened:
            await itm.open_setup("intermarche", HOME)
        with pytest.raises(HardBlockError) as searched:
            await search
        return opened.value, searched.value

    opened, searched = asyncio.run(scenario())
    assert loads == []
    assert opened.retry_after == searched.retry_after
    assert itm.hard_blocks.record("intermarche").seconds == 30 * 60  # not doubled
    assert itm.status().setup_mode is False
    clear_blocks(itm)


def test_store_finder(itm):
    async def scenario(page):
        await fresh(page)
        await page.route("https://www.intermarche.com/api/service/pdvs/**", as_json(fixtures.INTERMARCHE_STORES))
        return await SCRAPERS["intermarche"].find_stores(page, 43.6, 3.87)

    assert [s.id for s in run(itm, scenario)] == ["06814", "08012"]


def test_open_the_window_then_done(itm):
    clear_blocks(itm)

    async def prepare(page):
        await fresh(page)
        await page.route("https://geo.captcha-delivery.com/**", html(fixtures.DATADOME_CAPTCHA_FRAME))

    run(itm, prepare)
    asyncio.run(itm.open_setup("intermarche", HOME))
    status = itm.status()
    assert status.setup_mode is True and status.setup_store == "intermarche"
    assert status.running is False  # never the shared browser for Intermarché

    async def url(page):
        return page.url

    assert run(itm, url) == HOME
    assert asyncio.run(itm.end_setup()) == "intermarche"
    assert itm.status().setup_mode is False
    assert itm._real["intermarche"].challenge_pending is False

    # The check is still shown when the user says « J'ai terminé »: noted for the next time
    async def captcha(page):
        await page.unroute_all(behavior="ignoreErrors")
        await page.route("**/*", lambda route: route.abort())
        await page.route("https://geo.captcha-delivery.com/**", html(fixtures.DATADOME_CAPTCHA_FRAME))
        await page.route(HOME, html(fixtures.DATADOME_CAPTCHA_PAGE))
        await page.goto(HOME)

    run(itm, captcha)
    asyncio.run(itm.open_setup("intermarche", HOME))
    assert asyncio.run(itm.end_setup()) == "intermarche"
    assert itm._real["intermarche"].challenge_pending is True


def test_open_on_a_hard_block_page(itm):
    clear_blocks(itm)

    async def prepare(page):
        await fresh(page, fixtures.DATADOME_BLOCK_PAGE)
        await page.route("https://geo.captcha-delivery.com/**", html(fixtures.DATADOME_BLOCK_FRAME))

    run(itm, prepare)
    with pytest.raises(HardBlockError) as error:
        asyncio.run(itm.open_setup("intermarche", HOME))
    assert "temporairement" in str(error.value)
    assert itm.status().setup_mode is False
    clear_blocks(itm)


def test_launch_flags_of_the_window(itm):
    real = itm._real["intermarche"]
    if real._proc is None:
        pytest.skip("Chrome reused: started by another test")
    cmdline = Path(f"/proc/{real._proc.pid}/cmdline")
    if not cmdline.exists():
        pytest.skip("no /proc on this system")
    args = cmdline.read_bytes().decode().split("\0")[1:-1]
    port = parse_port_file((real.profile_dir / PORT_FILE).read_text())
    assert args == [
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={real.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-minimized",
        *sandbox_args(),
        "about:blank",
    ]
    assert real.profile_dir.name == "chrome-intermarche"


def test_old_intermarche_cookies_are_removed_once_from_the_shared_profile(tmp_path):
    manager = BrowserManager(tmp_path / "profile")

    async def add(page):
        later = time.time() + 3600  # saved in the profile (not session cookies)
        await page.context.add_cookies(
            [
                {"name": "datadome", "value": "old", "domain": ".intermarche.com", "path": "/", "expires": later},
                {"name": "itm_usid", "value": "old", "domain": "www.intermarche.com", "path": "/", "expires": later},
                {"name": "datadome", "value": "x", "domain": ".captcha-delivery.com", "path": "/", "expires": later},
                {"name": "session", "value": "keep", "domain": ".aldi.fr", "path": "/", "expires": later},
            ]
        )

    async def names(page):
        return sorted((c["domain"], c["name"]) for c in await page.context.cookies())

    try:
        asyncio.run(manager.run("aldi", add, timeout=60))
    except BrowserUnavailable as e:
        browser_missing(f"Chromium unavailable: {e}")
    mark = tmp_path / "profile" / "prixmalin-intermarche-oublie.txt"
    assert mark.exists()  # first launch of this profile: nothing to remove yet
    mark.unlink()  # a profile used by the previous version of PrixMalin
    asyncio.run(manager.shutdown())
    asyncio.run(manager.run("aldi", _noop, timeout=60))
    assert asyncio.run(manager.run("aldi", names, timeout=10)) == [(".aldi.fr", "session")]
    assert mark.exists()
    # Done once: an Intermarché cookie added later is left alone
    asyncio.run(manager.run("aldi", add, timeout=10))
    asyncio.run(manager.shutdown())
    asyncio.run(manager.run("aldi", _noop, timeout=60))
    assert (".intermarche.com", "datadome") in asyncio.run(manager.run("aldi", names, timeout=10))
    asyncio.run(manager.shutdown())


async def _noop(page):
    return True


def test_window_closed_by_the_user_opens_again_at_the_next_search(itm):
    real = itm._real["intermarche"]

    async def close_window(page):
        # What happens when the user closes the Chrome window: Chrome quits
        session = await real._browser.new_browser_cdp_session()
        await session.send("Browser.close")

    run(itm, close_window)
    for _ in range(50):
        if not real.running:
            break
        time.sleep(0.1)
    assert real.running is False
    assert itm.status().windows[0].closed_by_user is True
    assert run(itm, _blank) == "about:blank"
    assert real.running is True
    assert itm.status().windows[0].closed_by_user is False


def test_done_after_the_user_closed_the_window(itm):
    """« J'ai terminé » pressed after closing the window still names the retailer shown."""
    clear_blocks(itm)
    run(itm, fresh)
    asyncio.run(itm.open_setup("intermarche", HOME))
    real = itm._real["intermarche"]

    async def close_window(page):
        session = await real._browser.new_browser_cdp_session()
        await session.send("Browser.close")

    run(itm, close_window)
    for _ in range(50):
        if not real.running:
            break
        time.sleep(0.1)
    assert itm.status().setup_mode is False
    assert asyncio.run(itm.end_setup()) == "intermarche"
    assert asyncio.run(itm.end_setup()) is None  # pressed twice: nothing shown any more
    assert real.running is False  # « J'ai terminé » does not start Chrome again


def test_window_kept_when_prixmalin_restarts(itm, tmp_path):
    """A second PrixMalin (after a restart) reuses the Chrome window still open."""
    first = itm._real["intermarche"]
    asyncio.run(itm.run("intermarche", _blank, timeout=60))
    pid = first._proc.pid if first._proc else None
    again = BrowserManager(tmp_path / "profile", real_chrome_dir=first.profile_dir.parent)
    try:
        assert asyncio.run(again.run("intermarche", _blank, timeout=60)) == "about:blank"
        second = again._real["intermarche"]
        assert second._proc is None  # no new Chrome started
        assert second.running
    finally:
        asyncio.run(again.shutdown())  # closes that Chrome: the module's manager starts a new one
    for _ in range(50):
        if not first.running:
            break
        time.sleep(0.1)
    assert run(itm, _blank) == "about:blank"
    assert first._proc is not None and first._proc.pid != pid


def test_shared_browser_does_not_open_intermarche(tmp_path, monkeypatch):
    """Even its warm-up list cannot send the shared browser to intermarche.com."""
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche",))
    from backend.services import warmup

    assert "intermarche" not in warmup.WARMED_UP
    assert re.search("intermarche", " ".join(warmup.WARMED_UP)) is None


def test_window_started_for_a_search_goes_to_the_taskbar(tmp_path, monkeypatch):
    """Chrome has no --start-minimized switch: PrixMalin minimizes the window itself."""
    from backend.real_chrome import RealChrome
    from tests.p3_chrome import chrome_path, display

    path = chrome_path()
    if path is None:
        browser_missing("Chromium introuvable pour la fenêtre Intermarché")
    states = []
    original = RealChrome._set_window_state

    async def spy(self, page, state, only_from=None):
        states.append(state)
        await original(self, page, state, only_from)

    monkeypatch.setattr(RealChrome, "_set_window_state", spy)
    monkeypatch.setattr(config, "CHROME_PATH", path)
    monkeypatch.setattr(config, "CHROME_EXTRA_ARGS", sandbox_args())
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche",))
    with display() as available:
        if not available:
            browser_missing("pas d'écran pour la fenêtre Intermarché (installez Xvfb)")
        manager = BrowserManager(tmp_path / "profile", real_chrome_dir=tmp_path)
        try:
            asyncio.run(manager.run("intermarche", _blank, timeout=60))
            assert states == ["minimized"]  # started for a search: never left in front
            asyncio.run(manager.open_setup("intermarche", "about:blank"))
            assert states == ["minimized", "normal"]  # « Ouvrir le site »: shown again
        finally:
            asyncio.run(manager.shutdown())
        states.clear()
        visible = BrowserManager(tmp_path / "profile2", real_chrome_dir=tmp_path / "other")
        try:
            asyncio.run(visible.open_setup("intermarche", "about:blank"))
            assert "minimized" not in states  # started by « Ouvrir le site »: a normal window
        finally:
            asyncio.run(visible.shutdown())


def test_a_search_given_up_while_chrome_starts_still_minimizes_it(tmp_path, monkeypatch):
    """The start of the window goes on when the search that asked for it is cancelled (B43)."""
    import threading

    from backend.real_chrome import RealChrome
    from tests.p3_chrome import chrome_path, display

    path = chrome_path()
    if path is None:
        browser_missing("Chromium introuvable pour la fenêtre Intermarché")
    states = []
    spawned = threading.Event()
    original_state, original_wait = RealChrome._set_window_state, RealChrome._wait_endpoint

    async def spy(self, page, state, only_from=None):
        states.append(state)
        await original_state(self, page, state, only_from)

    async def wait_endpoint(self, port, proc):
        endpoint = await original_wait(self, port, proc)
        spawned.set()  # Chrome is running, PrixMalin is about to connect to it
        await asyncio.sleep(0.3)
        return endpoint

    monkeypatch.setattr(RealChrome, "_set_window_state", spy)
    monkeypatch.setattr(RealChrome, "_wait_endpoint", wait_endpoint)
    monkeypatch.setattr(config, "CHROME_PATH", path)
    monkeypatch.setattr(config, "CHROME_EXTRA_ARGS", sandbox_args())
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche",))

    async def scenario(manager):
        first = asyncio.create_task(manager.run("intermarche", _blank, timeout=60))
        # Chrome is started on the browser thread: wait for it from here
        assert await asyncio.to_thread(spawned.wait, 40)
        first.cancel()  # the client went away while Chrome was starting
        with pytest.raises(asyncio.CancelledError):
            await first
        return await manager.run("intermarche", _blank, timeout=60)

    with display() as available:
        if not available:
            browser_missing("pas d'écran pour la fenêtre Intermarché (installez Xvfb)")
        manager = BrowserManager(tmp_path / "profile", real_chrome_dir=tmp_path)
        try:
            assert asyncio.run(scenario(manager)) == "about:blank"
            real = manager._real["intermarche"]
            assert states == ["minimized"]  # minimized although its search was given up
            assert real._proc is not None and real.running  # one Chrome, still connected
        finally:
            asyncio.run(manager.shutdown())
