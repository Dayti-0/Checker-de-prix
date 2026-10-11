"""B44: queue per retailer with priorities, own time limit of the queue, shared visits, client gone."""

import asyncio
import time

import pytest

from backend import config
from backend.browser import BrowserManager, QueueTimeout, browser
from backend.models import Product
from backend.scrapers.base import BlockedError, HardBlockError
from backend.services import circuit, search
from tests.conftest import run


class Tab:
    """Stands for the tab of a retailer (no real browser needed)."""

    url = "about:blank"

    def is_closed(self):
        return False


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "MIN_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(config, "REQUEST_INTERVAL_SECONDS", {})
    monkeypatch.setattr(config, "REQUEST_JITTER_SECONDS", 0)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    m = BrowserManager(tmp_path / "profile")

    async def tab(key):
        return Tab()

    monkeypatch.setattr(m, "_get_page", tab)
    yield m
    asyncio.run(m.shutdown())


def test_the_queue_has_its_own_time_limit(manager):
    async def slow(page):
        await asyncio.sleep(3)
        return "lent"

    async def quick(page):
        return "rapide"

    async def scenario():
        first = asyncio.create_task(manager.run("aldi", slow, timeout=10))
        await asyncio.sleep(0.2)
        start = time.monotonic()
        second = await manager.run("aldi", quick, timeout=2)  # waits 3 s in the queue, works at once
        return await first, second, time.monotonic() - start

    first, second, waited = asyncio.run(scenario())
    assert (first, second) == ("lent", "rapide")
    assert waited > 2.5


def test_too_long_in_the_queue(manager, monkeypatch):
    monkeypatch.setattr(config, "QUEUE_TIMEOUT_SECONDS", 0.5)

    async def slow(page):
        await asyncio.sleep(2)

    async def quick(page):
        return "rapide"

    async def scenario():
        first = asyncio.create_task(manager.run("aldi", slow, timeout=10))
        await asyncio.sleep(0.1)
        with pytest.raises(QueueTimeout):
            await manager.run("aldi", quick, timeout=10)
        await first
        # The tab is free again for the next one
        return await manager.run("aldi", quick, timeout=10)

    assert asyncio.run(scenario()) == "rapide"


def test_interactive_search_goes_before_the_background_work(manager):
    order = []

    def task(name, seconds=0.05):
        async def fn(page):
            order.append(name)
            await asyncio.sleep(seconds)

        return fn

    async def scenario():
        running = asyncio.create_task(manager.run("aldi", task("courante", 0.6), timeout=10))
        await asyncio.sleep(0.15)
        jobs = [running]
        for name, priority in (("fond 1", "background"), ("fond 2", "background"), ("panier", "basket")):
            jobs.append(asyncio.create_task(manager.run("aldi", task(name), timeout=10, priority=priority)))
            await asyncio.sleep(0.05)
        jobs.append(asyncio.create_task(manager.run("aldi", task("recherche"), timeout=10)))
        await asyncio.gather(*jobs)

    asyncio.run(scenario())
    assert order == ["courante", "recherche", "panier", "fond 1", "fond 2"]


def test_other_retailers_do_not_wait(manager):
    async def slow(page):
        await asyncio.sleep(1.5)

    async def quick(page):
        return "ok"

    async def scenario():
        first = asyncio.create_task(manager.run("aldi", slow, timeout=10))
        await asyncio.sleep(0.1)
        start = time.monotonic()
        assert await manager.run("lidl", quick, timeout=5) == "ok"
        elapsed = time.monotonic() - start
        await first
        return elapsed

    assert asyncio.run(scenario()) < 0.5


def test_identical_searches_share_one_visit(monkeypatch):
    visits = []

    async def scrape(scraper, query, store):
        visits.append(query)
        await asyncio.sleep(0.3)
        scraper.last_source = "api"
        return [Product(store=scraper.key, name="Farine", price=0.75)]

    monkeypatch.setattr(search, "_scrape", scrape)

    async def scenario():
        return await asyncio.gather(*(search.search_store("lidl", q) for q in ("farine", "Farine ", "farine")))

    results = run(scenario())
    assert len(visits) == 1
    assert all(r.status == "ok" and r.products for r in results)


def test_a_search_does_not_join_a_lower_priority_visit(monkeypatch):
    visits = []

    async def scrape(scraper, query, store):
        visits.append(search._priority.get())
        await asyncio.sleep(0.2)
        return [Product(store=scraper.key, name="Farine", price=0.75)]

    monkeypatch.setattr(search, "_scrape", scrape)

    async def scenario():
        background = asyncio.create_task(search.search_store("lidl", "farine", True, priority="background"))
        await asyncio.sleep(0.05)
        await search.search_store("lidl", "farine", True)
        await background

    run(scenario())
    assert visits == ["background", "interactive"]


def test_one_cancelled_search_does_not_stop_the_shared_visit(monkeypatch):
    visits = []

    async def scrape(scraper, query, store):
        visits.append(query)
        await asyncio.sleep(0.4)
        return [Product(store=scraper.key, name="Farine", price=0.75)]

    monkeypatch.setattr(search, "_scrape", scrape)

    async def scenario():
        first = asyncio.create_task(search.search_store("lidl", "farine"))
        second = asyncio.create_task(search.search_store("lidl", "farine"))
        await asyncio.sleep(0.1)
        first.cancel()
        return await second

    assert run(scenario()).status == "ok"
    assert len(visits) == 1


class LeavingClient:
    """A request whose client goes away after ``after`` seconds."""

    def __init__(self, after):
        self.gone_at = time.monotonic() + after

    async def is_disconnected(self):
        return time.monotonic() >= self.gone_at


def test_client_gone_frees_the_tab_quickly(monkeypatch, tmp_path):
    from backend.api.search import until_disconnected

    monkeypatch.setattr(config, "BROWSER_PROFILE_DIR", tmp_path / "profile")

    async def tab(key):
        return Tab()

    monkeypatch.setattr(browser, "_get_page", tab)
    started = []

    async def long_visit(page):
        started.append(time.monotonic())
        await asyncio.sleep(30)

    async def scrape(scraper, query, store):
        return await browser.run(scraper.key, long_visit, timeout=60)

    monkeypatch.setattr(search, "_scrape", scrape)

    async def quick(page):
        return time.monotonic()

    async def scenario():
        result = await until_disconnected(LeavingClient(0.3), search.search_store("aldi", "farine"))
        gone = time.monotonic()
        free_at = await browser.run("aldi", quick, timeout=5)
        return result, free_at - gone

    try:
        result, delay = run(scenario())
    finally:
        asyncio.run(browser.shutdown())
    assert result is None and started
    assert delay < 1.0  # the tab is free again in less than a second


# --- a refusal of the site stops the calls already waiting (B41, B47) ------------------


def test_calls_waiting_behind_a_hard_block_send_nothing(manager):
    calls = []

    async def site_call(page, query):
        calls.append(query)
        await asyncio.sleep(0.2)  # the API answers 403 t=bv after a while
        raise HardBlockError("bloqué", label="Intermarché")

    async def scenario():
        runs = (manager.run("intermarche", site_call, f"q{i}", timeout=10) for i in range(5))
        return await asyncio.gather(*runs, return_exceptions=True)

    errors = asyncio.run(scenario())
    assert calls == ["q0"]
    assert all(isinstance(e, HardBlockError) for e in errors)
    record = manager.hard_blocks.record("intermarche")
    assert record.seconds == 30 * 60  # one block: not doubled by the waiting calls
    assert {e.retry_after for e in errors} == {record.until}
    assert all("ne réessaiera pas avant" in str(e) for e in errors)


def test_calls_waiting_behind_a_check_send_nothing(manager):
    calls = []

    async def site_call(page, query):
        calls.append(query)
        await asyncio.sleep(0.2)
        raise BlockedError("Intermarché demande une vérification")

    async def scenario():
        runs = (manager.run("intermarche", site_call, f"q{i}", timeout=10) for i in range(4))
        errors = await asyncio.gather(*runs, return_exceptions=True)
        # A call asked after the check is known goes (the circuit of search decides)
        with pytest.raises(BlockedError):
            await manager.run("intermarche", site_call, "after", timeout=10)
        return errors

    errors = asyncio.run(scenario())
    assert calls == ["q0", "after"]
    assert all(type(e) is BlockedError for e in errors)
    assert {str(e) for e in errors} == {"Intermarché demande une vérification"}
    assert manager.hard_blocks.active() == {}


def test_other_retailers_go_on_after_a_hard_block(manager):
    calls = []

    async def refused(page):
        calls.append("intermarche")
        await asyncio.sleep(0.2)
        raise HardBlockError("bloqué")

    async def fine(page, key):
        calls.append(key)
        return key

    async def scenario():
        first = asyncio.create_task(manager.run("intermarche", refused, timeout=10))
        await asyncio.sleep(0.05)
        other = await manager.run("lidl", fine, "lidl", timeout=10)
        with pytest.raises(HardBlockError):
            await first
        return other

    assert asyncio.run(scenario()) == "lidl"
    assert calls == ["intermarche", "lidl"]


def test_two_intermarche_searches_in_a_row_make_one_call(monkeypatch):
    from backend.models import StoreSelection
    from backend.scrapers import SCRAPERS
    from backend.scrapers.intermarche import check_answer
    from backend.services import settings as settings_service

    api_calls = []

    async def tab(key):
        return Tab()

    async def search_api(page, query, store):
        api_calls.append(query)  # one POST to the API of intermarche.com
        await asyncio.sleep(0.3)
        check_answer(403, '{"url":"https://geo.captcha-delivery.com/captcha/?initialCid=x&cid=y&t=bv"}')

    monkeypatch.setattr(browser, "_get_page", tab)
    monkeypatch.setattr(SCRAPERS["intermarche"], "search", search_api)

    async def scenario():
        await settings_service.set_store("intermarche", StoreSelection(id="06814", name="Lattes"))
        results = await asyncio.gather(*(search.search_store("intermarche", q) for q in ("farine", "huile")))
        saved = await circuit.HardBlocks(persist=True).get("intermarche")  # PrixMalin restarted
        return results, saved

    try:
        results, saved = run(scenario())
    finally:
        asyncio.run(browser.shutdown())
    assert api_calls == ["farine"]
    assert [r.status for r in results] == ["blocked", "blocked"]
    assert {r.retry_after for r in results} == {saved.until}
    assert saved.seconds == 30 * 60
