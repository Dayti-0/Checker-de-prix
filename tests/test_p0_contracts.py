"""B07: the extension contracts between the lots (CLAUDE.md, « Contrats d'extension »)."""

import asyncio
import inspect
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import backend
from backend import api, browser, database, main, models
from backend.models import BrowserStatus, ListItemCreate, Product, StoreResult, StoreSelection
from backend.scrapers import SCRAPERS, common
from backend.scrapers.base import SOURCES
from backend.services import basket, hooks, matching, prefs, search, shopping_list
from backend.services import settings as settings_service
from tests.conftest import run


@pytest.fixture
def listeners():
    """Listeners added by a test are removed after it."""
    offs = []
    yield lambda event, fn: offs.append(hooks.on(event, fn))
    for off in offs:
        off()


def fake_scrape(products, calls=None):
    async def scrape(scraper, query, store):
        if calls is not None:
            calls.append(scraper.key)
        scraper.last_source = "api"
        return [p.model_copy() for p in products]

    return scrape


# --- hooks -------------------------------------------------------------------


def test_a_failing_listener_does_not_break_the_event(listeners, caplog):
    received = []

    def broken(**kwargs):
        raise RuntimeError("bug in a listener")

    async def async_listener(**kwargs):
        received.append(("async", kwargs))

    listeners("custom", broken)
    listeners("custom", lambda **kwargs: received.append(("sync", kwargs)))
    listeners("custom", async_listener)
    asyncio.run(hooks.emit("custom", value=1))
    assert received == [("sync", {"value": 1}), ("async", {"value": 1})]
    assert "bug in a listener" in caplog.text


def test_listener_can_be_removed():
    received = []
    off = hooks.on("custom", lambda **kw: received.append(kw))
    off()
    off()  # twice is harmless
    asyncio.run(hooks.emit("custom", value=1))
    assert received == []


def test_search_events(monkeypatch, listeners):
    events = []
    listeners("search_finished", lambda **kw: events.append(("search_finished", kw)))
    listeners("products_scraped", lambda **kw: events.append(("products_scraped", kw)))
    monkeypatch.setattr(search, "_scrape", fake_scrape([Product(store="aldi", name="Farine T55", price=0.79)]))

    async def scenario():
        await settings_service.set_store("intermarche", StoreSelection(id="06814"))
        first = await search.search_store("aldi", "farine")
        second = await search.search_store("aldi", "farine")  # from the cache
        await search.search_store("intermarche", "farine")
        return first, second

    first, second = run(scenario())
    names = [name for name, _ in events]
    assert names == ["products_scraped", "search_finished", "search_finished", "products_scraped", "search_finished"]
    scraped = events[0][1]
    assert scraped["store"] == "aldi" and scraped["store_ctx"] == "" and scraped["query"] == "farine"
    assert [p.name for p in scraped["products"]] == ["Farine T55"]
    assert events[1][1]["result"] is first and events[1][1]["from_cache"] is False
    assert events[2][1]["result"] is second and events[2][1]["from_cache"] is True
    assert events[3][1]["store_ctx"] == "06814"


def test_basket_event(monkeypatch, listeners):
    received = []
    listeners("basket_compared", lambda comparison: received.append(comparison))
    monkeypatch.setattr(search, "_scrape", fake_scrape([Product(store="aldi", name="Farine", price=1.0)]))

    async def scenario():
        await shopping_list.add_item(ListItemCreate(query="farine"))
        return await basket.compare_basket(["aldi"])

    comparison = run(scenario())
    assert received == [comparison]


def test_startup_hooks_run_in_the_background():
    started = []

    async def hook():
        started.append(True)

    hooks.on_startup(hook)
    hooks.on_startup(hook)  # registered once
    try:
        assert hooks.startup_hooks().count(hook) == 1
        with TestClient(main.create_app()):
            pass
        assert started == [True]
    finally:
        hooks._startup.remove(hook)


def test_backup_providers_of_p0():
    assert {"settings", "shopping_list"} <= set(hooks.backups())

    async def scenario():
        export_settings, restore_settings = hooks.backups()["settings"]
        export_list, restore_list = hooks.backups()["shopping_list"]
        await settings_service.set_show_browser(True)
        await shopping_list.add_item(ListItemCreate(query="farine", quantity=2))
        saved = (await export_settings(), await export_list())
        await settings_service.set_show_browser(False)
        await shopping_list.clear()
        await shopping_list.add_item(ListItemCreate(query="sucre"))
        await restore_settings(saved[0])
        await restore_list(saved[1])
        return saved, await settings_service.load_settings(), await shopping_list.get_list()

    saved, current, items = run(scenario())
    assert "settings" in saved[0]
    assert current.show_browser is True
    assert [(i.query, i.quantity) for i in items] == [("farine", 2)]


# --- prefs -------------------------------------------------------------------


class Display(BaseModel):
    theme: str = "auto"
    scale: float = 1.0
    seen: list[str] = []


def test_prefs_defaults_and_update():
    async def scenario():
        before = await prefs.get("display", Display)
        changed = await prefs.update("display", Display, lambda p: setattr(p, "theme", "dark"))

        async def replace(p):
            return Display(theme=p.theme, scale=1.25)

        replaced = await prefs.update("display", Display, replace)
        return (
            before,
            changed,
            replaced,
            await prefs.get("display", Display),
            await database.get_setting("pref:display"),
        )

    before, changed, replaced, after, raw = run(scenario())
    assert before == Display()
    assert changed.theme == "dark"
    assert replaced == after == Display(theme="dark", scale=1.25)
    assert '"scale":1.25' in raw


def test_concurrent_prefs_updates_are_all_kept():
    async def add(name):
        async def fn(p):
            await asyncio.sleep(0.01)  # read, wait, write: no update may be lost
            p.seen.append(name)

        await prefs.update("display", Display, fn)

    async def scenario():
        await asyncio.gather(add("a"), add("b"), add("c"))
        return await prefs.get("display", Display)

    assert sorted(run(scenario()).seen) == ["a", "b", "c"]


# --- models and contract fields ------------------------------------------------


def test_contract_fields_are_optional():
    product = Product(store="aldi", name="Farine")
    assert (product.ean, product.sku) == (None, None)
    result = StoreResult(store="aldi", label="Aldi", status="ok")
    assert (result.fetched_at, result.stale, result.source) == (None, False, None)
    assert BrowserStatus(running=False, headless=True, setup_mode=False).is_local is False


def test_models_are_reexported():
    for area in ("products", "search", "settings", "browser", "shopping", "status", "tracking"):
        module = getattr(models, area)
        for name in module.__all__:
            assert getattr(models, name) is getattr(module, name)


def test_search_result_tells_when_and_how(monkeypatch):
    monkeypatch.setattr(search, "_scrape", fake_scrape([Product(store="lidl", name="Farine", price=0.75)]))

    async def scenario():
        before = time.time()
        fresh = await search.search_store("lidl", "farine")
        cached = await search.search_store("lidl", "farine")
        return before, fresh, cached

    before, fresh, cached = run(scenario())
    assert fresh.source == "api" and fresh.fetched_at >= before and not fresh.cached
    assert cached.cached and cached.fetched_at == pytest.approx(fresh.fetched_at, abs=1)
    # B46 (P3): the cache remembers how the products were read
    assert cached.source == "api" and cached.stale is False


def test_search_store_signature():
    params = inspect.signature(search.search_store).parameters
    assert list(params)[:3] == ["key", "query", "refresh"]
    assert params["priority"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["priority"].default == "interactive"


def test_match_score_is_the_relevance():
    assert matching.match_score("Farine de blé T45", "farine") == 1.0
    assert matching.match_score("Huile de tournesol", "huile d'olive") == matching.relevance(
        "Huile de tournesol", "huile d'olive"
    )


def test_every_scraper_has_a_source():
    assert SOURCES == ("api", "html", "generic", "json-ld")
    for scraper in SCRAPERS.values():
        assert scraper.last_source is None or scraper.last_source in SOURCES
        assert scraper.found([], "api") == [] and scraper.last_source is None
        products = [Product(store=scraper.key, name="x")]
        assert scraper.found(products, "html") is products and scraper.last_source == "html"
        scraper.last_source = None


def test_snapshot_path(tmp_path):
    # B48 (P3): timestamped names, {key}-{AAAAMMJJ-HHMMSS}-{status}.html
    when = datetime(2026, 10, 3, 14, 0, 0)
    assert common.snapshot_path("aldi", "empty", when) == tmp_path / "debug" / "aldi-20261003-140000-empty.html"
    assert common.snapshot_path("aldi", "blocked", when) == tmp_path / "debug" / "aldi-20261003-140000-blocked.html"


# --- browser -------------------------------------------------------------------


def test_browser_contract():
    assert browser.CHANNEL_ORDER == ("chrome", "msedge", "chromium")
    assert browser.PLAYWRIGHT_INSTALL_ARGS == ("-m", "playwright", "install", "chromium")
    assert browser.PRIORITIES == ("interactive", "basket", "background")
    params = inspect.signature(browser.BrowserManager.run).parameters
    assert params["timeout"].default is None and params["priority"].default == "interactive"
    assert browser.browser.context_generation >= 0


def test_browser_run_rejects_an_unknown_priority(tmp_path):
    manager = browser.BrowserManager(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(manager.run("aldi", lambda page: None, priority="urgent"))


def test_calls_to_a_retailer_are_spaced(tmp_path, monkeypatch):
    """The politeness delay only waits for what is left of the interval."""
    manager = browser.BrowserManager(tmp_path)
    monkeypatch.setattr(browser.config, "MIN_REQUEST_INTERVAL_SECONDS", 0.6)

    async def get_page(key):
        return "page"

    async def visit(page):
        return time.monotonic()

    manager._get_page = get_page

    async def scenario():
        manager._last_request["aldi"] = time.monotonic() - 10  # long ago: no wait
        start = time.monotonic()
        first = await manager._run_on_page("aldi", visit, ())
        second = await manager._run_on_page("aldi", visit, ())  # right after: waits
        return first - start, second - first

    no_wait, wait = asyncio.run(scenario())
    assert no_wait < 0.3
    assert 0.6 <= wait < 2.0  # interval + jitter (at most 0.5 s), on a slow machine too


def test_browser_status_says_if_the_request_is_local():
    with TestClient(main.app, client=("127.0.0.1", 50000)) as local:
        assert local.get("/api/browser").json()["is_local"] is True
    with TestClient(main.app, client=("192.168.1.20", 50000)) as phone:
        assert phone.get("/api/browser").json()["is_local"] is False


# --- app ---------------------------------------------------------------------


def test_routers_list_is_fixed():
    names = [m.__name__.rsplit(".", 1)[1] for m in api.ROUTERS]
    assert names == [
        "search",
        "retailers",
        "settings",
        "browser",
        "shopping_list",
        "basket",
        "system",
        "status",
        "tracking",
        "backup",
        "updates",
    ]


def test_version():
    with TestClient(main.app) as client:
        assert client.get("/api/version").json() == {"version": backend.__version__}
    assert main.app.version == backend.__version__


def test_database_reexports_the_repos():
    from backend.repos import cache, settings_store
    from backend.repos import shopping_list as list_repo

    assert database.get_cached is cache.get_cached
    assert database.set_setting is settings_store.set_setting
    assert database.clear_items is list_repo.clear_items
    with pytest.raises(AttributeError):
        _ = database.unknown_function


def test_entry_points_of_p7():
    from backend import instance, logging_setup, security

    assert instance.ensure_single_instance() is None
    assert logging_setup.configure() is None
    assert callable(security.install)
