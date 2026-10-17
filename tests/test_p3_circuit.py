"""B47: circuit breaker per retailer and store, hard block pause, warm-up."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.browser import browser
from backend.models import BlockRecord, Product, Settings, StoreSelection
from backend.scrapers.base import BlockedError, HardBlockError, StoreRequiredError
from backend.services import circuit, search, warmup
from backend.services import settings as settings_service
from backend.services.circuit import CircuitState, after_result, may_call
from tests.conftest import run

NOW = 1_000_000.0


def counting(result, calls):
    """A fake ``_scrape``: counts the visits, returns products or raises ``result``."""

    async def scrape(scraper, query, store):
        calls.append((scraper.key, query, store.id if store else None))
        if isinstance(result, BaseException):
            raise result
        scraper.last_source = "api"
        return [Product(store=scraper.key, name=name, price=price) for name, price in result]

    return scrape


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    async def never(*args, **kwargs):
        raise AssertionError("no real browser in these tests")

    monkeypatch.setattr(browser, "run", never)


# --- pure decisions -----------------------------------------------------------------


def test_circuit_opens_after_a_check_or_store_required():
    for status in ("blocked", "store_required"):
        state = after_result(None, status, "message", NOW)
        assert (state.reason, state.until) == (status, NOW + 600)
        assert not may_call(state, NOW + 599, refresh=False, priority="interactive", dedicated=False)
        assert may_call(state, NOW + 601, refresh=False, priority="interactive", dedicated=False)


def test_circuit_opens_after_two_timeouts_in_a_row():
    one = after_result(None, "timeout", "lent", NOW)
    assert one.timeouts == 1 and one.until == 0
    two = after_result(one, "timeout", "lent", NOW + 5)
    assert (two.reason, two.until, two.timeouts) == ("timeout", NOW + 5 + 120, 2)
    # A success in between starts the count again
    assert after_result(after_result(one, "ok", None, NOW + 1), "timeout", "lent", NOW + 2).timeouts == 1
    # An error (site unreachable) changes nothing
    assert after_result(one, "error", "x", NOW + 1) == one


def test_who_may_go_through_an_open_circuit():
    blocked = CircuitState("blocked", NOW + 600, 0, "blocked", "m")
    # A search asked again by the user goes through
    assert may_call(blocked, NOW, refresh=True, priority="interactive", dedicated=False)
    # Not the basket nor the background work
    assert not may_call(blocked, NOW, refresh=True, priority="basket", dedicated=False)
    assert not may_call(blocked, NOW, refresh=True, priority="background", dedicated=False)
    # Intermarché: only « Ouvrir le site » then « J'ai terminé » reopens it
    assert not may_call(blocked, NOW, refresh=True, priority="interactive", dedicated=True)
    store = CircuitState("store_required", NOW + 600, 0, "store_required", "m")
    assert may_call(store, NOW, refresh=True, priority="interactive", dedicated=True)


# --- search_store ---------------------------------------------------------------------


def test_five_searches_on_a_blocked_retailer_visit_the_site_once(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", counting(BlockedError("Carrefour demande une vérification"), calls))

    async def scenario():
        return [await search.search_store("carrefour", f"farine {i % 2}") for i in range(5)]

    results = run(scenario())
    assert len(calls) == 1
    assert {r.status for r in results} == {"blocked"}
    assert results[-1].message == "Carrefour demande une vérification"


def test_refresh_goes_through_except_for_an_unvalidated_intermarche_check(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", counting(BlockedError("vérification"), calls))
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche",))

    async def scenario():
        await settings_service.set_store("intermarche", StoreSelection(id="06814", name="Lattes"))
        for key in ("carrefour", "intermarche"):
            await search.search_store(key, "farine")
            await search.search_store(key, "farine", refresh=True)
            await search.search_store(key, "farine", refresh=True, priority="basket")

    run(scenario())
    assert [c[0] for c in calls] == ["carrefour", "carrefour", "intermarche"]


def test_store_required_then_another_store(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", counting(StoreRequiredError("Choisissez votre magasin"), calls))

    async def scenario():
        first = await search.search_store("intermarche", "farine")
        again = await search.search_store("intermarche", "farine")
        await settings_service.set_store("intermarche", StoreSelection(id="06814", name="Lattes"))
        other = await search.search_store("intermarche", "farine")
        return first, again, other

    first, again, other = run(scenario())
    assert (first.status, again.status) == ("store_required", "store_required")
    assert len(calls) == 2 and calls[1][2] == "06814"  # the new store is visited at once
    assert other.status == "store_required"


def test_products_without_price_are_shown_again_while_open(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", counting([("Farine", None)], calls))

    async def scenario():
        return await search.search_store("coursesu", "farine"), await search.search_store("coursesu", "farine")

    first, second = run(scenario())
    assert len(calls) == 1
    assert first.status == second.status == "store_required"
    assert [p.name for p in second.products] == ["Farine"]


def test_two_timeouts_open_the_circuit(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", counting(TimeoutError(), calls))

    async def scenario():
        return [await search.search_store("lidl", "farine") for _ in range(4)]

    results = run(scenario())
    assert len(calls) == 2
    assert [r.status for r in results] == ["timeout"] * 4
    assert results[0].message == "Le site Lidl met trop de temps à répondre."


def test_retailer_state(monkeypatch):
    monkeypatch.setattr(search, "_scrape", counting(BlockedError("vérification"), []))

    async def scenario():
        before = await search.retailer_state("aldi")
        await search.search_store("aldi", "farine")
        return before, await search.retailer_state("aldi")

    before, after = run(scenario())
    assert before.circuit_open is False and before.reason is None
    assert after.circuit_open is True and after.reason == "blocked" and after.until > 0
    assert after.last_blocked is not None  # noted for the warm-up


def test_done_reopens_the_circuit_of_the_retailer(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", counting(BlockedError("vérification"), calls))

    async def fake_open(key, url):
        browser.setup_mode, browser.setup_store = True, key

    async def fake_end():
        store, browser.setup_store, browser.setup_mode = browser.setup_store, None, False
        return store

    monkeypatch.setattr(browser, "open_setup", fake_open)
    monkeypatch.setattr(browser, "end_setup", fake_end)
    from backend import main

    with TestClient(main.app) as client:
        assert client.get("/api/search/aldi", params={"q": "farine"}).json()["status"] == "blocked"
        assert client.get("/api/search/lidl", params={"q": "farine"}).json()["status"] == "blocked"
        client.get("/api/search/aldi", params={"q": "farine"})
        assert len(calls) == 2
        assert client.post("/api/browser/setup", json={"store": "aldi"}).status_code == 200
        assert client.post("/api/browser/setup/done").status_code == 200
        client.get("/api/search/aldi", params={"q": "farine"})
        client.get("/api/search/lidl", params={"q": "farine"})
    assert [c[0] for c in calls] == ["aldi", "lidl", "aldi"]  # Lidl stays paused


# --- hard block -----------------------------------------------------------------------


def test_no_visit_during_a_hard_block(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_scrape", counting(HardBlockError("bloqué", label="Intermarché"), calls))

    async def scenario():
        await settings_service.set_store("intermarche", StoreSelection(id="06814", name="Lattes"))
        first = await search.search_store("intermarche", "farine")
        others = [await search.search_store("intermarche", q, refresh=True) for q in ("farine", "lait")]
        state = await search.retailer_state("intermarche")
        return first, others, state

    first, others, state = run(scenario())
    assert len(calls) == 1
    assert first.status == "blocked" and first.retry_after is not None
    assert "ne réessaiera pas avant" in first.message
    for result in others:
        assert result.status == "blocked" and result.retry_after == first.retry_after
    assert state.reason == "hard_block" and state.hard_block_until == first.retry_after


def test_hard_block_pause_is_kept_in_the_database(monkeypatch):
    monkeypatch.setattr(search, "_scrape", counting(HardBlockError("bloqué"), []))

    async def scenario():
        await search.search_store("carrefour", "farine")
        fresh = circuit.HardBlocks(persist=True)  # PrixMalin restarted
        return await fresh.until("carrefour")

    assert run(scenario()) is not None


# --- warm-up --------------------------------------------------------------------------


def test_warmup_targets():
    settings = Settings()
    assert warmup.warmup_targets(settings, {}, NOW) == ["carrefour", "lidl"]
    # Intermarché is never opened at startup, even with a store, even listed
    configured = Settings(stores={"intermarche": StoreSelection(id="06814")})
    assert warmup.warmup_targets(configured, {}, NOW, keys=("intermarche", "lidl")) == ["lidl"]
    # A retailer that needs a store is skipped while none is chosen
    assert warmup.warmup_targets(settings, {}, NOW, keys=("coursesu", "lidl")) == ["lidl"]
    with_store = Settings(stores={"coursesu": StoreSelection(url="https://www.coursesu.com/drive-x")})
    assert warmup.warmup_targets(with_store, {}, NOW, keys=("coursesu",)) == ["coursesu"]
    # Blocked or checked in the last 24 hours: left alone
    recent = {"carrefour": BlockRecord(last_blocked=NOW - 3600)}
    assert warmup.warmup_targets(settings, recent, NOW) == ["lidl"]
    old = {"carrefour": BlockRecord(last_blocked=NOW - 25 * 3600)}
    assert warmup.warmup_targets(settings, old, NOW) == ["carrefour", "lidl"]
    paused = {"lidl": BlockRecord(until=NOW + 60, last_blocked=NOW - 30 * 3600)}
    assert warmup.warmup_targets(settings, paused, NOW) == ["carrefour"]
    # A retailer with its own Chrome window is never warmed up
    assert warmup.warmup_targets(settings, {}, NOW, dedicated=("lidl",)) == ["carrefour"]


def test_warmup_opens_only_the_allowed_sites(monkeypatch):
    opened = []

    async def fake_warmup(targets):
        opened.append(dict(targets))

    monkeypatch.setenv("PRIXMALIN_WARMUP", "1")
    monkeypatch.setattr(browser, "warmup", fake_warmup)

    async def scenario():
        await browser.hard_blocks.blocked("carrefour")
        await warmup.warmup_once()

    run(scenario())
    assert opened == [{"lidl": "https://www.lidl.fr/"}]
    assert all("intermarche" not in url for targets in opened for url in targets.values())


def test_warmup_disabled(monkeypatch):
    opened = []

    async def fake_warmup(targets):
        opened.append(targets)

    monkeypatch.setenv("PRIXMALIN_WARMUP", "0")
    monkeypatch.setattr(browser, "warmup", fake_warmup)
    run(warmup.warmup_once())
    assert opened == []


def test_circuits_of_another_database_are_closed(tmp_path, monkeypatch):
    breaker = circuit.Circuit()
    breaker.update("aldi", "", "blocked", "m")
    assert breaker.get("aldi", "") is not None
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "other.db")
    assert breaker.get("aldi", "") is None


def test_unknown_priority_is_refused():
    with pytest.raises(ValueError):
        asyncio.run(search.search_store("aldi", "farine", priority="urgent"))
