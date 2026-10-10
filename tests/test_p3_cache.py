"""B46: resilient search cache (fresh, refreshed in the background, older prices when the site fails)."""

import asyncio
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.browser import browser
from backend.models import Product, StoreSelection
from backend.repos import cache
from backend.scrapers import SCRAPERS
from backend.scrapers.base import BlockedError, HardBlockError
from backend.services import search
from backend.services import settings as settings_service
from tests.conftest import run

HOUR = 3600


def farine(store, price=0.75):
    return Product(store=store, name="Farine de blé", price=price)


class FakeSite:
    """A fake ``_scrape``: answers ``self.answer`` (products or an exception), counts the visits."""

    def __init__(self, answer):
        self.answer = answer
        self.visits: list[tuple[str, str, str]] = []

    async def __call__(self, scraper, query, store):
        self.visits.append((scraper.key, query, search._priority.get()))
        if isinstance(self.answer, BaseException):
            raise self.answer
        scraper.last_source = "api"
        return [p.model_copy() for p in self.answer]


@pytest.fixture
def site(monkeypatch):
    fake = FakeSite([farine("lidl")])
    monkeypatch.setattr(search, "_scrape", fake)

    async def never(*args, **kwargs):
        raise AssertionError("no real browser in these tests")

    monkeypatch.setattr(browser, "run", never)
    return fake


def key(store, query="farine", selection=None):
    return search.cache_key(SCRAPERS[store], selection, query)


async def save(store, age, products=None, source="api", query="farine"):
    products = [farine(store)] if products is None else products
    await cache.set_cached(
        key(store, query), [p.model_dump() for p in products], source=source, created_at=time.time() - age
    )


# --- the repository -------------------------------------------------------------------


def test_reading_never_deletes():
    async def scenario():
        await save("lidl", 8 * HOUR)
        expired = await cache.get_cached(key("lidl"))
        entry = await cache.get_entry(key("lidl"))
        recent = await cache.get_entry(key("lidl"), max_age=HOUR)
        return expired, entry, recent

    expired, entry, recent = run(scenario())
    assert expired is None  # older than 6 h: not fresh...
    assert entry is not None and entry.source == "api"  # ...but still there
    assert entry[0][0]["name"] == "Farine de blé" and entry[1] < time.time() - 7 * HOUR
    assert recent is None


def test_get_cached_gives_products_and_time():
    async def scenario():
        await save("lidl", 60)
        return await cache.get_cached(key("lidl"))

    products, created_at = run(scenario())
    assert products[0]["name"] == "Farine de blé"
    assert time.time() - created_at == pytest.approx(60, abs=5)


def test_rows_of_prixmalin_2_are_read():
    entry = cache.decode('[{"store": "aldi", "name": "Farine"}]', 12.0)
    assert entry == ([{"store": "aldi", "name": "Farine"}], 12.0, None)
    assert cache.decode("not json", 1.0) is None
    assert cache.decode('{"products": "x"}', 1.0) is None
    assert cache.decode('{"products": [1]}', 1.0) is None


def test_purge_removes_entries_older_than_seven_days():
    async def scenario():
        await save("lidl", 8 * 24 * HOUR)
        await save("aldi", 6 * 24 * HOUR)
        removed = await cache.purge_cache()
        return removed, await cache.get_entry(key("lidl")), await cache.get_entry(key("aldi"))

    removed, lidl, aldi = run(scenario())
    assert removed == 1 and lidl is None and aldi is not None


def test_purge_at_startup():
    async def scenario():
        await save("lidl", 8 * 24 * HOUR)

    run(scenario())
    from backend import main

    with TestClient(main.app):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if run(cache.get_entry(key("lidl"))) is None:
                break
            time.sleep(0.05)
    assert run(cache.get_entry(key("lidl"))) is None


def test_clear_cache_of_one_retailer_only():
    async def scenario():
        await save("lidl", 60)
        await save("aldi", 60)
        await cache.clear_cache("lidl|")
        return await cache.get_entry(key("lidl")), await cache.get_entry(key("aldi"))

    lidl, aldi = run(scenario())
    assert lidl is None and aldi is not None


# --- search_store ---------------------------------------------------------------------


def test_fresh_entry_is_served_without_visit(site):
    async def scenario():
        await save("lidl", 30 * 60)
        return await search.search_store("lidl", "farine")

    result = run(scenario())
    assert site.visits == []
    assert result.cached and not result.stale and result.status == "ok"
    assert result.source == "api" and time.time() - result.fetched_at == pytest.approx(1800, abs=5)


def test_entry_older_than_an_hour_is_served_then_refreshed_in_the_background(site):
    async def scenario():
        await save("lidl", 2 * HOUR)
        result = await search.search_store("lidl", "farine")
        await asyncio.gather(*search._refreshing)
        entry = await cache.get_entry(key("lidl"))
        return result, entry

    result, entry = run(scenario())
    assert result.cached and not result.stale
    assert site.visits == [("lidl", "farine", "background")]
    assert time.time() - entry.created_at < 60  # read again


def test_identical_background_refreshes_are_shared(site):
    async def scenario():
        await save("lidl", 2 * HOUR)
        await asyncio.gather(*(search.search_store("lidl", "farine") for _ in range(3)))
        await asyncio.gather(*search._refreshing)

    run(scenario())
    assert len(site.visits) == 1


def test_no_background_visit_for_intermarche(site, monkeypatch):
    monkeypatch.setattr(config, "REAL_CHROME_STORES", ("intermarche",))
    selection = StoreSelection(id="06814", name="Lattes")

    async def scenario():
        await settings_service.set_store("intermarche", selection)
        await cache.set_cached(
            key("intermarche", selection=selection),
            [farine("intermarche").model_dump()],
            created_at=time.time() - 2 * HOUR,
        )
        result = await search.search_store("intermarche", "farine")
        await asyncio.gather(*search._refreshing)
        return result

    assert run(scenario()).cached
    assert site.visits == []  # Intermarché is only visited when the user asks


def test_expired_entry_then_blocked_site_shows_the_older_prices(site):
    site.answer = BlockedError("Lidl demande une vérification")

    async def scenario():
        await save("lidl", 8 * HOUR)
        return await search.search_store("lidl", "farine")

    result = run(scenario())
    assert len(site.visits) == 1
    assert result.status == "ok" and result.stale and result.cached and result.problem == "blocked"
    assert [p.name for p in result.products] == ["Farine de blé"]
    saved = datetime.fromtimestamp(result.fetched_at)
    clock = f"{saved.hour} h" + (f" {saved.minute:02d}" if saved.minute else "")
    assert result.message == f"Prix du {saved:%d/%m} à {clock} (Lidl : vérification requise)"


@pytest.mark.parametrize(
    ("error", "problem", "words"),
    [
        (TimeoutError(), "timeout", "site trop lent"),
        (RuntimeError("boom"), "error", "site indisponible"),
    ],
)
def test_older_prices_after_a_timeout_or_an_error(site, error, problem, words):
    site.answer = error

    async def scenario():
        await save("lidl", 10 * HOUR)
        return await search.search_store("lidl", "farine")

    result = run(scenario())
    assert result.stale and result.problem == problem and words in result.message


def test_older_prices_during_a_hard_block(site):
    site.answer = HardBlockError("bloqué")

    async def scenario():
        await save("carrefour", 10 * HOUR)
        return await search.search_store("carrefour", "farine")

    result = run(scenario())
    assert result.stale and result.retry_after is not None
    assert "Carrefour : accès bloqué jusqu'à" in result.message


def test_refresh_that_fails_keeps_the_prices(site):
    site.answer = BlockedError("vérification")

    async def scenario():
        await save("lidl", 10 * 60)
        return await search.search_store("lidl", "farine", refresh=True)

    result = run(scenario())
    assert len(site.visits) == 1 and result.stale and result.products


def test_entry_older_than_seven_days_is_not_shown(site):
    site.answer = BlockedError("Lidl demande une vérification")

    async def scenario():
        await save("lidl", 8 * 24 * HOUR)
        return await search.search_store("lidl", "farine")

    result = run(scenario())
    assert result.status == "blocked" and result.products == [] and not result.stale


def test_no_cache_when_a_store_is_needed_and_no_price_is_shown(site):
    site.answer = [Product(store="coursesu", name="Farine U", price=None)]

    async def scenario():
        result = await search.search_store("coursesu", "farine")
        return result, await cache.get_entry(key("coursesu"))

    result, entry = run(scenario())
    assert result.status == "store_required" and entry is None


def test_no_product_is_remembered_thirty_minutes(site):
    site.answer = []

    async def scenario():
        first = await search.search_store("aldi", "farine")
        second = await search.search_store("aldi", "farine")
        await save("aldi", 31 * 60, products=[])
        third = await search.search_store("aldi", "farine")
        return first, second, third

    first, second, third = run(scenario())
    assert (first.status, second.status, third.status) == ("empty", "empty", "empty")
    assert second.cached and not third.cached
    assert len(site.visits) == 2


def test_unreadable_entry_counts_as_no_cache(site):
    async def scenario():
        await cache.set_cached(key("lidl"), [{"store": "lidl", "name": None}])
        return await search.search_store("lidl", "farine")

    result = run(scenario())
    assert len(site.visits) == 1 and not result.cached and result.status == "ok"


def test_fresh_result_has_time_and_source(site):
    before = time.time()
    result = run(search.search_store("lidl", "farine"))
    assert not result.cached and not result.stale
    assert result.fetched_at >= before and result.source == "api"
